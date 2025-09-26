from flask import Flask, request, jsonify, render_template
import requests
import json
import urllib.parse
from flask_cors import CORS
from search_es import SearchEs
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # 启用CORS

# 初始化SQLite数据库
def init_analyzed_songs_db():
    """初始化已分析歌曲数据库"""
    db_path = 'analyzed_songs.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建已分析歌曲表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analyzed_songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id TEXT NOT NULL,
            source TEXT NOT NULL,
            name TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT,
            lyricist TEXT,
            composer TEXT,
            platform_name TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            lyric_lines INTEGER DEFAULT 0,
            word_count INTEGER DEFAULT 0,
            has_lyrics BOOLEAN DEFAULT 0,
            UNIQUE(song_id, source)
        )
    ''')
    
    # 创建索引提升查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_analyzed_at ON analyzed_songs(analyzed_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_song_source ON analyzed_songs(song_id, source)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_name_artist ON analyzed_songs(name, artist)')
    
    conn.commit()
    conn.close()
    print("✅ 已分析歌曲数据库初始化完成（含性能优化索引）")

# 初始化数据库
init_analyzed_songs_db()

def add_analyzed_song(song_data):
    """添加已分析歌曲到数据库 - 异步处理"""
    import threading
    
    def save_to_db():
        try:
            conn = sqlite3.connect('analyzed_songs.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO analyzed_songs 
                (song_id, source, name, artist, album, lyricist, composer, platform_name, 
                 lyric_lines, word_count, has_lyrics, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                song_data.get('id'),
                song_data.get('source'),
                song_data.get('name', ''),
                song_data.get('artist', ''),
                song_data.get('album', ''),
                song_data.get('lyricist', ''),
                song_data.get('composer', ''),
                song_data.get('platform_name', ''),
                song_data.get('analysis', {}).get('lyric_lines', 0),
                song_data.get('analysis', {}).get('word_count', 0),
                song_data.get('analysis', {}).get('has_lyrics', False),
                datetime.now().isoformat()
            ))
            
            conn.commit()
            conn.close()
            print(f"✅ 已保存分析记录: {song_data.get('name')} - {song_data.get('artist')}")
        except Exception as e:
            print(f"❌ 保存分析记录失败: {e}")
    
    # 在后台线程中异步保存，不阻塞主请求
    thread = threading.Thread(target=save_to_db, daemon=True)
    thread.start()
    return True

def get_analyzed_songs(limit=50, offset=0):
    """获取已分析歌曲列表 - 优化版本"""
    try:
        conn = sqlite3.connect('analyzed_songs.db')
        conn.row_factory = sqlite3.Row  # 使用Row工厂获得更好的性能
        cursor = conn.cursor()
        
        # 获取总数（优化查询）
        cursor.execute('SELECT COUNT(*) FROM analyzed_songs')
        total = cursor.fetchone()[0]
        
        if total == 0:
            conn.close()
            return {'songs': [], 'total': 0}
        
        # 获取分页数据（添加索引优化）
        cursor.execute('''
            SELECT id, song_id, source, name, artist, album, lyricist, composer,
                   platform_name, analyzed_at, lyric_lines, word_count, has_lyrics
            FROM analyzed_songs 
            ORDER BY analyzed_at DESC 
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        
        songs = []
        for row in cursor.fetchall():
            songs.append({
                'record_id': row['id'],          # 数据库主键
                'id': row['song_id'],            # 原始歌曲ID
                'source': row['source'],
                'name': row['name'],
                'artist': row['artist'],
                'album': row['album'],
                'lyricist': row['lyricist'],
                'composer': row['composer'],
                'platform_name': row['platform_name'],
                'analyzed_at': row['analyzed_at'],
                'analysis': {
                    'lyric_lines': row['lyric_lines'],
                    'word_count': row['word_count'],
                    'has_lyrics': bool(row['has_lyrics'])
                }
            })
        
        conn.close()
        return {'songs': songs, 'total': total}
    except Exception as e:
        print(f"❌ 获取已分析歌曲失败: {e}")
        return {'songs': [], 'total': 0}

# 创建本地搜索实例
try:
    local_searcher = SearchEs()
    print("✅ 本地Elasticsearch连接成功")
except Exception as e:
    local_searcher = None
    print(f"❌ 本地Elasticsearch连接失败: {e}")

def search_local_elasticsearch(query, limit=10):
    """搜索本地Elasticsearch数据库"""
    if not local_searcher:
        return []
    
    try:
        results = []
        
        # 搜索歌曲名
        song_results = local_searcher.search_song(query)
        for hit in song_results[:limit]:
            source = hit['_source']
            results.append({
                'id': hit['_id'],
                'name': source.get('song', ''),
                'artist': source.get('singer', ''),
                'album': source.get('album', ''),
                'lyricist': source.get('author', ''),
                'composer': source.get('composer', ''),
                'lyric_id': hit['_id'],
                'source': 'local',
                'platform': 'local',
                'platform_name': '本地数据库',
                'pic_id': hit['_id'],
                'lyric_text': source.get('geci', '')
            })
        
        # 如果结果不足，搜索歌手
        if len(results) < limit:
            singer_results = local_searcher.search_singer(query)
            for hit in singer_results[:limit-len(results)]:
                source = hit['_source']
                if hit['_id'] not in [r['id'] for r in results]:  # 避免重复
                    results.append({
                        'id': hit['_id'],
                        'name': source.get('song', ''),
                        'artist': source.get('singer', ''),
                        'album': source.get('album', ''),
                        'lyricist': source.get('author', ''),
                        'composer': source.get('composer', ''),
                        'lyric_id': hit['_id'],
                        'source': 'local',
                        'platform': 'local',
                        'platform_name': '本地数据库',
                        'pic_id': hit['_id'],
                        'lyric_text': source.get('geci', '')
                    })
        
        # 如果结果还不足，搜索歌词
        if len(results) < limit:
            lyric_results = local_searcher.search_geci(query)
            for hit in lyric_results[:limit-len(results)]:
                source = hit['_source']
                if hit['_id'] not in [r['id'] for r in results]:  # 避免重复
                    results.append({
                        'id': hit['_id'],
                        'name': source.get('song', ''),
                        'artist': source.get('singer', ''),
                        'album': source.get('album', ''),
                        'lyricist': source.get('author', ''),
                        'composer': source.get('composer', ''),
                        'lyric_id': hit['_id'],
                        'source': 'local',
                        'platform': 'local',
                        'platform_name': '本地数据库',
                        'pic_id': hit['_id'],
                        'lyric_text': source.get('geci', '')
                    })
        
        print(f"本地搜索 '{query}' 找到 {len(results)} 首歌曲")
        return results
        
    except Exception as e:
        print(f"本地搜索失败: {e}")
        return []

class MusicAPIProxy:
    """基于cl-music-main项目的音乐API代理类"""
    
    def __init__(self):
        # 支持多个API端点作为备选
        self.api_endpoints = [
            "https://music-api.gdstudio.xyz/api.php",
            "https://api.liumingye.cn/music/api.php",
            "https://music.aityp.com/api.php"
        ]
        self.current_api = 0
        
        # 支持的音乐平台 - 优化版本，只保留网易云和QQ音乐
        self.platforms = {
            'netease': '网易云音乐',
            'qq': 'QQ音乐'
        }
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Origin': 'https://music.gdstudio.xyz',
            'Referer': 'https://music.gdstudio.xyz/'
        }
        
    def _make_request(self, params, retry_count=0):
        """发送API请求，支持多个端点重试"""
        if retry_count >= len(self.api_endpoints):
            return None
            
        api_base = self.api_endpoints[self.current_api]
        
        try:
            print(f"尝试API端点: {api_base}")
            print(f"请求参数: {params}")
            
            response = requests.get(api_base, params=params, headers=self.headers, timeout=15)
            print(f"响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"响应数据: {data}")
                    return data
                except json.JSONDecodeError:
                    print("JSON解析失败")
                    return None
            else:
                print(f"API请求失败，状态码: {response.status_code}")
                
        except Exception as e:
            print(f"请求异常: {e}")
            
        # 切换到下一个API端点重试
        self.current_api = (self.current_api + 1) % len(self.api_endpoints)
        return self._make_request(params, retry_count + 1)
        
    def search_music(self, query, source='netease', count=20, pages=1):
        """搜索音乐 - 支持多平台"""
        try:
            # 验证平台是否支持
            if source not in self.platforms:
                print(f"不支持的音乐平台: {source}")
                return []
                
            params = {
                'types': 'search',
                'source': source,
                'name': query,
                'count': count,
                'pages': pages
            }
            
            data = self._make_request(params)
            if data is None:
                return []
                
            # 处理返回的数据格式
            results = []
            if isinstance(data, list):
                for song in data:
                    results.append({
                        'id': song.get('id'),
                        'name': song.get('name'),
                        'artist': song.get('artist'),
                        'album': song.get('album'),
                        'pic_id': song.get('pic_id'),
                        'lyric_id': song.get('lyric_id'),
                        'source': song.get('source', source),
                        'platform': source,
                        'platform_name': self.platforms.get(source, source),
                        'lyricist': song.get('lyricist', ''),  # 作词
                        'composer': song.get('composer', ''),  # 作曲
                        'duration': song.get('duration', ''),  # 时长
                    })
            return results
                
        except Exception as e:
            print(f"搜索音乐失败: {e}")
            return []
    
    def get_music_url(self, music_id, source, br='999'):
        """获取音乐播放链接"""
        try:
            params = {
                'types': 'url',
                'source': source,
                'id': music_id,
                'br': br
            }
            
            data = self._make_request(params)
            if data and isinstance(data, dict):
                return data.get('url', '')
            return ''
            
        except Exception as e:
            print(f"获取音乐链接失败: {e}")
            return ''
    
    def get_lyrics(self, lyric_id, source):
        """获取歌词"""
        try:
            params = {
                'types': 'lyric',
                'source': source,
                'id': lyric_id
            }
            
            data = self._make_request(params)
            if data and isinstance(data, dict):
                return {
                    'lyric': data.get('lyric', ''),
                    'tlyric': data.get('tlyric', '')
                }
            return {'lyric': '', 'tlyric': ''}
            
        except Exception as e:
            print(f"获取歌词失败: {e}")
            return {'lyric': '', 'tlyric': ''}
    
    def get_cover(self, source, pic_id, size=300):
        """获取专辑封面"""
        try:
            params = {
                'types': 'pic',
                'source': source,
                'id': pic_id,
                'size': size
            }
            
            data = self._make_request(params)
            if data and isinstance(data, dict):
                return data.get('url', '')
            return ''
            
        except Exception as e:
            print(f"获取封面失败: {e}")
            return ''

# 创建API代理实例
music_api = MusicAPIProxy()

class BackupMusicSearcher:
    """备用音乐搜索器 - 当主API不可用时使用"""
    
    def __init__(self):
        self.apis = [
            {
                'name': '网易云音乐API',
                'url': 'https://music.163.com/api/search/get/web',
                'platform': 'netease'
            }
        ]
    
    def search_netease_backup(self, query, limit=10):
        """备用网易云音乐搜索"""
        try:
            url = "https://music.163.com/api/search/get/web"
            params = {
                'csrf_token': '',
                's': query,
                'type': 1,
                'offset': 0,
                'total': True,
                'limit': limit
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://music.163.com/'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('result') and data['result'].get('songs'):
                    results = []
                    for song in data['result']['songs'][:limit]:
                        artists = [artist['name'] for artist in song.get('artists', [])]
                        results.append({
                            'id': str(song['id']),
                            'name': song['name'],
                            'artist': ', '.join(artists),
                            'album': song.get('album', {}).get('name', ''),
                            'pic_id': str(song['id']),
                            'lyric_id': str(song['id']),
                            'source': 'netease',
                            'platform': 'netease',
                            'platform_name': '网易云音乐',
                            'lyricist': '',  # 网易云API通常不直接提供作词信息
                            'composer': '',  # 网易云API通常不直接提供作曲信息
                            'duration': song.get('duration', 0)
                        })
                    return results
            return []
        except Exception as e:
            print(f"备用网易云搜索失败: {e}")
            return []
    
    def search_mock_data(self, query, limit=5):
        """模拟搜索数据 - 用于演示"""
        try:
            # 创建一些模拟数据用于演示
            mock_songs = [
                {
                    'id': f'mock_{query}_1',
                    'name': f'{query} - 精选版',
                    'artist': '知名歌手',
                    'album': '热门专辑',
                    'pic_id': 'mock_pic_1',
                    'lyric_id': 'mock_lyric_1',
                    'source': 'demo',
                    'platform': 'demo',
                    'platform_name': '演示平台',
                    'lyricist': '优秀作词人',
                    'composer': '才华作曲家',
                    'duration': 240000
                },
                {
                    'id': f'mock_{query}_2',
                    'name': f'关于{query}的歌',
                    'artist': '流行歌手',
                    'album': '最新单曲',
                    'pic_id': 'mock_pic_2',
                    'lyric_id': 'mock_lyric_2',
                    'source': 'demo',
                    'platform': 'demo',
                    'platform_name': '演示平台',
                    'lyricist': '创意作词人',
                    'composer': '新锐作曲家',
                    'duration': 210000
                }
            ]
            return mock_songs[:limit]
        except Exception as e:
            print(f"模拟数据生成失败: {e}")
            return []

backup_searcher = BackupMusicSearcher()

def find_lyric_matches(lyric_text, query):
    """在歌词中查找关键词匹配位置"""
    matches = []
    if not lyric_text or not query:
        return matches
    
    try:
        # 清理歌词文本，移除时间标记
        import re
        clean_lyric = re.sub(r'\[\d+:\d+\.\d+\]', '', lyric_text)
        clean_lyric = clean_lyric.strip()
        
        lines = clean_lyric.split('\n')
        query_lower = query.lower()
        
        for i, line in enumerate(lines):
            line_clean = line.strip()
            if not line_clean:
                continue
                
            if query_lower in line_clean.lower():
                # 找到匹配的行
                start_pos = line_clean.lower().find(query_lower)
                matches.append({
                    'line_number': i + 1,
                    'line_text': line_clean,
                    'start_pos': start_pos,
                    'match_text': line_clean[start_pos:start_pos + len(query)]
                })
        
        return matches[:5]  # 最多返回5个匹配位置
    except Exception as e:
        print(f"歌词匹配失败: {e}")
        return []

@app.route('/')
def index():
    """主页"""
    return render_template('index_optimized.html')

@app.route('/song_detail_page/<song_id>')
def song_detail_page(song_id):
    """歌曲详细信息页面"""
    return render_template('song_detail.html')

@app.route('/song_analysis/<song_id>')
def song_analysis_page(song_id):
    """新的歌曲分析页面"""
    return render_template('song_analysis.html')

@app.route('/api', methods=['GET'])
def api_proxy():
    """API代理端点 - 模仿cl-music-main的API结构"""
    try:
        # 获取请求参数
        types = request.args.get('types')
        source = request.args.get('source', 'netease')
        
        if types == 'search':
            # 搜索音乐
            name = request.args.get('name', '')
            count = int(request.args.get('count', 20))
            pages = int(request.args.get('pages', 1))
            
            if not name:
                return jsonify({'error': '搜索关键词不能为空'}), 400
            
            results = music_api.search_music(name, source, count, pages)
            return jsonify(results)
            
        elif types == 'url':
            # 获取音乐播放链接
            music_id = request.args.get('id')
            br = request.args.get('br', '999')
            
            if not music_id:
                return jsonify({'error': '音乐ID不能为空'}), 400
                
            url = music_api.get_music_url(music_id, source, br)
            return jsonify({'url': url})
            
        elif types == 'lyric':
            # 获取歌词
            lyric_id = request.args.get('id')
            
            if not lyric_id:
                return jsonify({'error': '歌词ID不能为空'}), 400
                
            lyrics = music_api.get_lyrics(lyric_id, source)
            return jsonify(lyrics)
            
        elif types == 'pic':
            # 获取专辑封面
            pic_id = request.args.get('id')
            size = int(request.args.get('size', 300))
            
            if not pic_id:
                return jsonify({'error': '图片ID不能为空'}), 400
                
            cover_url = music_api.get_cover(source, pic_id, size)
            return jsonify({'url': cover_url})
            
        else:
            return jsonify({'error': '不支持的API类型'}), 400
            
    except Exception as e:
        print(f"API代理错误: {e}")
        return jsonify({'error': '服务器内部错误'}), 500

@app.route('/search', methods=['GET'])
def search():
    """搜索接口 - 优先本地数据库，在线API作为补充"""
    try:
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 20))
        
        if not query:
            return jsonify({'error': '搜索关键词不能为空', 'results': []})
        
        print(f"开始混合搜索: {query}, 限制: {limit}")
        
        # 先搜索本地数据库
        local_results = search_local_elasticsearch(query, limit)
        all_results = local_results.copy()
        search_summary = {'local': len(local_results)}
        
        # 如果本地结果不足，补充在线结果
        if len(local_results) < 5:
            print(f"本地结果不足({len(local_results)}首)，补充在线搜索...")
            
            # 只搜索网易云和QQ音乐平台（提升速度）
            sources = ['netease', 'qq']
            online_results = []
            
            for src in sources:
                try:
                    print(f"搜索平台: {src}")
                    results = music_api.search_music(query, src, 10, 1)  # 增加每个平台搜索数量
                    
                    # 如果主API返回空结果，尝试备用搜索
                    if not results and src == 'netease':
                        print(f"主API搜索 {src} 无结果，尝试备用API...")
                        results = backup_searcher.search_netease_backup(query, 10)
                    
                    search_summary[src] = len(results)
                    online_results.extend(results)
                    print(f"平台 {src} 返回 {len(results)} 首歌曲")
                    
                except Exception as e:
                    print(f"搜索 {src} 失败: {e}")
                    search_summary[src] = 0
                    continue
            
            all_results.extend(online_results)
        else:
            print(f"本地搜索结果充足({len(local_results)}首)，跳过在线搜索")
        
        print(f"搜索汇总: {search_summary}")
        print(f"总计找到 {len(all_results)} 首歌曲")
        
        # 快速去重并限制数量
        unique_results = []
        seen = set()
        for song in all_results:
            # 处理歌手字段 - 有时是列表，有时是字符串
            artist = song.get('artist', '')
            if isinstance(artist, list):
                artist_str = ', '.join(artist)
            else:
                artist_str = str(artist)
            
            # 使用歌曲名和歌手名作为唯一标识
            name_str = str(song.get('name', '')).lower().strip()
            artist_key = artist_str.lower().strip()
            key = f"{name_str}-{artist_key}"
            
            if key not in seen and key != '-' and name_str:
                seen.add(key)
                # 确保返回的数据中artist字段是字符串
                song['artist'] = artist_str
                
                # 不在搜索时获取歌词，提高响应速度
                song['lyric_matches'] = []
                song['has_lyric_match'] = False
                
                unique_results.append(song)
                if len(unique_results) >= limit:
                    break
        
        print(f"去重后返回 {len(unique_results)} 首歌曲")
        
        # 如果没有找到任何结果，提供一些演示数据
        if len(unique_results) == 0:
            print("没有找到真实结果，提供演示数据...")
            unique_results = backup_searcher.search_mock_data(query, 5)
        
        return jsonify({
            'query': query,
            'count': len(unique_results),
            'total_found': len(all_results),
            'platforms_searched': len(search_summary),
            'search_summary': search_summary,
            'local_count': len(local_results),
            'results': unique_results
        })
        
    except Exception as e:
        print(f"搜索错误: {e}")
        return jsonify({'error': '搜索失败', 'results': []})

@app.route('/suggest', methods=['GET'])
def search_suggest():
    """搜索建议接口 - 为输入框提供实时建议"""
    try:
        query = request.args.get('q', '').strip()
        limit = int(request.args.get('limit', 6))  # 减少建议数量
        
        if not query or len(query) < 2:
            return jsonify({'suggestions': []})
        
        print(f"获取搜索建议: {query}")
        
        # 优先搜索本地数据库，然后搜索网易云（提高速度）
        all_results = []
        
        # 先尝试本地搜索建议
        if local_searcher:
            try:
                local_suggestions = search_local_elasticsearch(query, 3)  # 本地搜索3首
                all_results.extend(local_suggestions)
                print(f"本地建议: {len(local_suggestions)}首")
            except:
                pass
        
        # 如果本地建议不足，补充网易云建议
        if len(all_results) < limit:
            try:
                results = music_api.search_music(query, 'netease', 6, 1)  # 只搜索网易云
                all_results.extend(results)
                print(f"网易云建议: {len(results)}首")
            except:
                pass
        
        # 快速去重
        unique_suggestions = []
        seen = set()
        
        for song in all_results:
            artist = song.get('artist', '')
            if isinstance(artist, list):
                artist_str = ', '.join(artist)
            else:
                artist_str = str(artist)
            
            name_str = str(song.get('name', '')).strip()
            key = f"{name_str}-{artist_str}".lower()
            
            if key not in seen and name_str:
                seen.add(key)
                suggestion = {
                    'id': song.get('id'),
                    'name': name_str,
                    'artist': artist_str,
                    'album': song.get('album', ''),
                    'platform': song.get('platform', ''),
                    'platform_name': song.get('platform_name', ''),
                    'source': song.get('source', ''),
                    'pic_id': song.get('pic_id', ''),
                    'lyric_id': song.get('lyric_id', ''),
                    'lyricist': song.get('lyricist', ''),
                    'composer': song.get('composer', '')
                }
                unique_suggestions.append(suggestion)
                
                if len(unique_suggestions) >= limit:
                    break
        
        return jsonify({
            'query': query,
            'suggestions': unique_suggestions
        })
        
    except Exception as e:
        print(f"搜索建议错误: {e}")
        return jsonify({'suggestions': []})

@app.route('/lyrics', methods=['GET'])
def get_lyrics():
    """获取歌词接口 - 优先本地数据库"""
    try:
        lyric_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        
        if not lyric_id:
            return jsonify({'error': '歌词ID不能为空'})
        
        # 如果是本地数据库的歌曲，直接从本地获取歌词
        if source == 'local' and local_searcher:
            try:
                # 通过ID获取本地歌词
                result = local_searcher.es.get(index="music_data", id=lyric_id)
                lyric_text = result['_source'].get('geci', '')
                return jsonify({
                    'lyric': lyric_text,
                    'tlyric': ''  # 本地数据库没有翻译歌词
                })
            except Exception as e:
                print(f"本地歌词获取失败: {e}")
        
        # 否则使用在线API获取歌词
        lyrics = music_api.get_lyrics(lyric_id, source)
        return jsonify(lyrics)
        
    except Exception as e:
        print(f"获取歌词错误: {e}")
        return jsonify({'error': '获取歌词失败'})

@app.route('/lyric_match', methods=['GET'])
def get_lyric_match():
    """获取歌词匹配接口 - 按需加载歌词匹配，支持本地数据库"""
    try:
        lyric_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        query = request.args.get('q', '').strip()
        
        if not lyric_id or not query:
            return jsonify({'error': '参数不完整', 'matches': []})
        
        # 获取歌词
        lyric_text = ''
        if source == 'local' and local_searcher:
            try:
                # 从本地数据库获取歌词
                result = local_searcher.es.get(index="music_data", id=lyric_id)
                lyric_text = result['_source'].get('geci', '')
            except Exception as e:
                print(f"本地歌词获取失败: {e}")
        else:
            # 从在线API获取歌词
            lyrics_data = music_api.get_lyrics(lyric_id, source)
            lyric_text = lyrics_data.get('lyric', '')
        
        # 查找匹配
        matches = find_lyric_matches(lyric_text, query)
        
        return jsonify({
            'lyric_id': lyric_id,
            'source': source,
            'query': query,
            'matches': matches,
            'has_match': len(matches) > 0,
            'full_lyric': lyric_text
        })
        
    except Exception as e:
        print(f"获取歌词匹配错误: {e}")
        return jsonify({'error': '获取歌词匹配失败', 'matches': []})

@app.route('/play_url', methods=['GET'])
def get_play_url():
    """获取播放链接接口"""
    try:
        music_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        quality = request.args.get('quality', '999')
        
        if not music_id:
            return jsonify({'error': '音乐ID不能为空'})
        
        url = music_api.get_music_url(music_id, source, quality)
        return jsonify({'url': url})
        
    except Exception as e:
        print(f"获取播放链接错误: {e}")
        return jsonify({'error': '获取播放链接失败'})

@app.route('/platforms', methods=['GET'])
def get_platforms():
    """获取支持的音乐平台列表"""
    try:
        platforms = music_api.platforms
        platform_list = [
            {'id': key, 'name': value, 'available': True} 
            for key, value in platforms.items()
        ]
        return jsonify({
            'platforms': platform_list,
            'count': len(platform_list)
        })
    except Exception as e:
        print(f"获取平台列表错误: {e}")
        return jsonify({'error': '获取平台列表失败'})

@app.route('/song_detail', methods=['GET'])
def get_song_detail():
    """获取歌曲详细信息接口"""
    try:
        song_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        
        if not song_id:
            return jsonify({'error': '歌曲ID不能为空'})
        
        # 如果是本地数据库的歌曲
        if source == 'local' and local_searcher:
            try:
                result = local_searcher.es.get(index="music_data", id=song_id)
                song_data = result['_source']
                
                # 分析歌词信息
                lyric_text = song_data.get('geci', '')
                lyric_lines = len([line for line in lyric_text.split('\n') if line.strip()])
                word_count = len(lyric_text.replace('\n', '').replace(' ', ''))
                
                song_detail = {
                    'id': song_id,
                    'name': song_data.get('song', ''),
                    'artist': song_data.get('singer', ''),
                    'album': song_data.get('album', ''),
                    'lyricist': song_data.get('author', ''),
                    'composer': song_data.get('composer', ''),
                    'source': 'local',
                    'platform_name': '本地数据库',
                    'lyric': lyric_text,
                    'analysis': {
                        'lyric_lines': lyric_lines,
                        'word_count': word_count,
                        'has_lyrics': bool(lyric_text.strip())
                    }
                }
                
                # 保存到已分析歌曲数据库
                add_analyzed_song(song_detail)
                
                return jsonify(song_detail)
            except Exception as e:
                print(f"获取本地歌曲详情失败: {e}")
                return jsonify({'error': '获取歌曲详情失败'})
        
        # 在线歌曲的详细信息
        else:
            try:
                # 先尝试从搜索结果中获取歌曲基本信息
                song_name = request.args.get('name', '未知歌曲')
                artist_name = request.args.get('artist', '未知歌手')
                album_name = request.args.get('album', '')
                lyricist_name = request.args.get('lyricist', '')
                composer_name = request.args.get('composer', '')
                
                # 获取歌词
                lyrics_data = music_api.get_lyrics(song_id, source)
                lyric_text = lyrics_data.get('lyric', '')
                
                # 分析歌词
                lyric_lines = len([line for line in lyric_text.split('\n') if line.strip()]) if lyric_text else 0
                word_count = len(lyric_text.replace('\n', '').replace(' ', '')) if lyric_text else 0
                
                # 获取封面（减小图片尺寸提升速度）
                cover_url = ''
                try:
                    cover_url = music_api.get_cover(source, song_id, 300)
                except:
                    pass  # 封面获取失败不影响主要功能
                
                song_detail = {
                    'id': song_id,
                    'name': song_name,
                    'artist': artist_name,
                    'album': album_name,
                    'lyricist': lyricist_name,
                    'composer': composer_name,
                    'source': source,
                    'platform_name': music_api.platforms.get(source, source),
                    'lyric': lyric_text,
                    'tlyric': lyrics_data.get('tlyric', ''),
                    'cover_url': cover_url,
                    'analysis': {
                        'lyric_lines': lyric_lines,
                        'word_count': word_count,
                        'has_lyrics': bool(lyric_text.strip())
                    }
                }
                
                # 异步保存到已分析歌曲数据库（不阻塞响应）
                add_analyzed_song(song_detail)
                
                return jsonify(song_detail)
            except Exception as e:
                print(f"获取在线歌曲详情失败: {e}")
                return jsonify({'error': '获取歌曲详情失败'})
        
    except Exception as e:
        print(f"获取歌曲详细信息错误: {e}")
        return jsonify({'error': '获取歌曲详细信息失败'})

@app.route('/song_info', methods=['GET'])
def get_song_info():
    """获取歌曲基本信息（供前端按需调用）"""
    try:
        song_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        
        if not song_id:
            return jsonify({'error': '歌曲ID不能为空'})
        
        # 搜索歌曲基本信息
        results = music_api.search_music(song_id, source, 1, 1)
        
        if results and len(results) > 0:
            song_info = results[0]
            return jsonify({
                'id': song_info.get('id'),
                'name': song_info.get('name', ''),
                'artist': song_info.get('artist', ''),
                'album': song_info.get('album', ''),
                'lyricist': song_info.get('lyricist', ''),
                'composer': song_info.get('composer', ''),
                'duration': song_info.get('duration', ''),
                'platform_name': song_info.get('platform_name', '')
            })
        else:
            return jsonify({'error': '未找到歌曲信息'})
            
    except Exception as e:
        print(f"获取歌曲信息错误: {e}")
        return jsonify({'error': '获取歌曲信息失败'})

@app.route('/analyzed_songs', methods=['GET'])
def get_analyzed_songs_api():
    """获取已分析歌曲列表"""
    try:
        page = int(request.args.get('page', 1))
        limit = min(int(request.args.get('limit', 20)), 50)  # 限制最大页面大小
        offset = (page - 1) * limit
        
        result = get_analyzed_songs(limit, offset)
        
        return jsonify({
            'success': True,
            'data': result['songs'],
            'total': result['total'],
            'page': page,
            'limit': limit,
            'total_pages': (result['total'] + limit - 1) // limit if result['total'] > 0 else 0
        })
    except Exception as e:
        print(f"获取已分析歌曲列表失败: {e}")
        return jsonify({'success': False, 'error': '获取列表失败'})

@app.route('/analyzed_songs_page')
def analyzed_songs_page():
    """已分析歌曲页面"""
    return render_template('analyzed_songs.html')

@app.route('/delete_analyzed_songs', methods=['POST'])
def delete_analyzed_songs():
    """删除已分析歌曲（需要密码验证）"""
    try:
        data = request.get_json()
        password = data.get('password')
        song_ids = data.get('song_ids', [])
        
        # 密码验证
        if password != 'ozh02264632':
            return jsonify({'success': False, 'error': '密码错误'})
        
        if not song_ids:
            return jsonify({'success': False, 'error': '未选择要删除的歌曲'})
        
        # 删除数据库记录
        conn = sqlite3.connect('analyzed_songs.db')
        cursor = conn.cursor()
        
        # 构建删除SQL
        placeholders = ','.join(['?' for _ in song_ids])
        cursor.execute(f'DELETE FROM analyzed_songs WHERE id IN ({placeholders})', song_ids)
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'成功删除 {deleted_count} 条记录',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        print(f"删除已分析歌曲失败: {e}")
        return jsonify({'success': False, 'error': '删除失败'})

@app.route('/cover', methods=['GET'])
def get_cover():
    """获取专辑封面接口"""
    try:
        pic_id = request.args.get('id')
        source = request.args.get('source', 'netease')
        size = int(request.args.get('size', 300))
        
        if not pic_id:
            return jsonify({'error': '图片ID不能为空'})
        
        cover_url = music_api.get_cover(source, pic_id, size)
        return jsonify({'url': cover_url})
        
    except Exception as e:
        print(f"获取封面错误: {e}")
        return jsonify({'error': '获取封面失败'})

if __name__ == '__main__':
    print("🎵 智能音乐搜索服务启动中...")
    print("🌐 基于cl-music-main项目架构，支持搜索建议和歌词匹配")
    print("📡 API端点: https://music-api.gdstudio.xyz/api.php")
    print("🎯 支持平台: 网易云音乐、QQ音乐（优化版本）")
    print("💡 优化策略: 本地数据库优先 + 双平台在线补充")
    print("🔗 访问地址: http://localhost:5002")
    app.run(debug=True, host='0.0.0.0', port=5002)
