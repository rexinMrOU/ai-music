from flask import Flask, render_template, request, jsonify
import requests
import json
import re
from urllib.parse import quote

app = Flask(__name__)

class OnlineMusicSearcher:
    def __init__(self):
        self.base_url = "https://music.163.com/api"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://music.163.com/'
        }
    
    def search_songs(self, keyword, limit=10):
        """搜索歌曲"""
        try:
            # 使用网易云音乐搜索API
            search_url = f"http://music.163.com/api/search/get/web"
            params = {
                'csrf_token': '',
                's': keyword,
                'type': 1,  # 1表示搜索歌曲
                'offset': 0,
                'total': True,
                'limit': limit
            }
            
            response = requests.get(search_url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('result') and data['result'].get('songs'):
                    songs = []
                    for song in data['result']['songs'][:limit]:
                        # 获取歌手名称
                        artists = [artist['name'] for artist in song.get('artists', [])]
                        artist_name = ', '.join(artists)
                        
                        songs.append({
                            'id': song['id'],
                            'name': song['name'],
                            'artist': artist_name,
                            'album': song.get('album', {}).get('name', ''),
                            'duration': song.get('duration', 0)
                        })
                    return songs
            return []
        except Exception as e:
            print(f"搜索歌曲错误: {e}")
            return []
    
    def get_song_detail(self, song_id):
        """获取歌曲详细信息"""
        try:
            # 获取歌曲详情
            detail_url = f"http://music.163.com/api/song/detail/"
            params = {'id': song_id, 'ids': f'[{song_id}]'}
            
            response = requests.get(detail_url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('songs') and len(data['songs']) > 0:
                    song = data['songs'][0]
                    artists = [artist['name'] for artist in song.get('artists', [])]
                    
                    return {
                        'id': song['id'],
                        'name': song['name'],
                        'artist': ', '.join(artists),
                        'album': song.get('album', {}).get('name', ''),
                        'duration': song.get('duration', 0),
                        'pic_url': song.get('album', {}).get('picUrl', '')
                    }
            return None
        except Exception as e:
            print(f"获取歌曲详情错误: {e}")
            return None

# 使用免费音乐API的备用方案
class FreeMusicSearcher:
    def __init__(self):
        self.qq_music_api = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://y.qq.com/'
        }
    
    def search_songs(self, keyword, limit=10):
        """使用QQ音乐API搜索歌曲"""
        try:
            params = {
                'ct': 24,
                'qqmusic_ver': 1298,
                'new_json': 1,
                'remoteplace': 'txt.yqq.center',
                'searchid': 0,
                'catZhida': 1,
                'format': 'json',
                'platform': 'yqq.json',
                'needNewCode': 0,
                't': 0,
                'aggr': 1,
                'cr': 1,
                'w': keyword,
                'p': 1,
                'n': limit
            }
            
            response = requests.get(self.qq_music_api, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                # 去除JSONP回调函数包装
                text = response.text
                if 'callback(' in text:
                    text = text.split('callback(')[1].rsplit(')', 1)[0]
                
                data = json.loads(text)
                if data.get('data') and data['data'].get('song') and data['data']['song'].get('list'):
                    songs = []
                    for song in data['data']['song']['list'][:limit]:
                        # 获取歌手名称
                        singers = [singer['name'] for singer in song.get('singer', [])]
                        singer_name = ', '.join(singers)
                        
                        songs.append({
                            'id': song.get('songmid', ''),
                            'name': song.get('songname', ''),
                            'artist': singer_name,
                            'album': song.get('albumname', ''),
                            'duration': song.get('interval', 0)
                        })
                    return songs
            return []
        except Exception as e:
            print(f"QQ音乐搜索错误: {e}")
            return []

# 初始化在线搜索器
online_searcher = FreeMusicSearcher()  # 使用免费的QQ音乐API

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_suggestions', methods=['POST'])
def search_suggestions():
    """根据输入的关键词返回候选歌曲"""
    try:
        query = request.json.get('query', '').strip()
        if not query:
            return jsonify({'suggestions': []})
        
        # 使用在线音乐API搜索歌曲
        results = online_searcher.search_songs(query, limit=5)
        
        suggestions = []
        for song in results:
            suggestions.append({
                'id': song['id'],
                'singer': song['artist'],
                'song': song['name'],
                'album': song['album'],
                'duration': song['duration']
            })
        
        return jsonify({'suggestions': suggestions})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_song_details', methods=['POST'])
def get_song_details():
    """获取歌曲信息 - 线上版本返回基本信息"""
    try:
        data = request.json
        song_id = data.get('id', '')
        singer = data.get('singer', '')
        song = data.get('song', '')
        
        if not song:
            return jsonify({'error': '缺少歌曲信息'}), 400
        
        # 对于线上版本，我们返回基本信息和提示
        return jsonify({
            'id': song_id,
            'singer': singer,
            'song': song,
            'album': data.get('album', ''),
            'duration': data.get('duration', 0),
            'message': '由于版权限制，暂不提供完整歌词显示',
            'suggestion': '您可以点击下方链接前往官方平台收听完整歌曲',
            'links': {
                'qq_music': f"https://y.qq.com/n/yqq/search?w={quote(singer + ' ' + song)}",
                'netease': f"https://music.163.com/#/search/m/?s={quote(singer + ' ' + song)}",
                'kugou': f"https://www.kugou.com/search?keyword={quote(singer + ' ' + song)}"
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/next_lyric', methods=['POST'])
def next_lyric():
    """歌词接龙功能 - 线上版本"""
    try:
        query = request.json.get('lyric', '').strip()
        if not query:
            return jsonify({'error': '请输入歌词'}), 400
        
        # 搜索包含该歌词的歌曲
        results = online_searcher.search_songs(query, limit=3)
        
        if not results:
            return jsonify({'message': '没找到包含该歌词的歌曲，可能是您创作的哦！'})
        
        # 返回可能的歌曲匹配
        suggestions = []
        for song in results:
            suggestions.append({
                'song': song['name'],
                'artist': song['artist'],
                'message': f"在《{song['name']}》中可能包含这句歌词"
            })
        
        return jsonify({
            'message': '由于版权限制，无法提供歌词接龙功能',
            'suggestions': suggestions,
            'tip': '建议前往官方音乐平台查看完整歌词'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
