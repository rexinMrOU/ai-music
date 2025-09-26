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
            SELECT song_id, source, name, artist, album, lyricist, composer, 
                   platform_name, analyzed_at, lyric_lines, word_count, has_lyrics
            FROM analyzed_songs 
            ORDER BY analyzed_at DESC 
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        
        songs = []
        for row in cursor.fetchall():
            songs.append({
                'id': row['song_id'],
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
    except Exception as e:
        return jsonify({'error': f'API处理异常: {str(e)}'}), 500
