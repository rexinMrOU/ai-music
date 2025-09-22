import React, { useState, useEffect, useRef,useCallback } from 'react';
import { Container, Row, Col, Form, Button, Card, Spinner, Dropdown } from 'react-bootstrap';
import axios from 'axios';
import ReactPlayer from 'react-player';
import { FaPlay, FaPause, FaDownload, FaMusic ,FaChevronDown,FaChevronUp,FaGithub } from 'react-icons/fa';
import { toast } from 'react-toastify';


const API_BASE = process.env.REACT_APP_API_BASE || '/api';


const Github = ()=>{
  return (
    <a
        href="https://github.com/lovebai/cl-music"
        target="_blank"
        rel="noopener noreferrer"
        className="github-corner"
        aria-label="View source on GitHub"
      >
        <FaGithub
          size={32}
          className="text-dark"
          style={{
            position: 'fixed',
            top: '20px',
            right: '20px',
            zIndex: 1000,
            transition: 'transform 0.3s ease'
          }}
        />
      </a>
  )
}

const MusicSearch = () => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [source, setSource] = useState('netease');
  const [quality, setQuality] = useState('999');
  const [loading, setLoading] = useState(false);
  const [currentTrack, setCurrentTrack] = useState(null);
  const [playerUrl, setPlayerUrl] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  const playerRef = useRef(null);
  const [coverCache, setCoverCache] = useState({});
  const [lyricData, setLyricData] = useState({
    rawLyric: '',
    tLyric: '',
    parsedLyric: []
  });
  const [currentLyricIndex, setCurrentLyricIndex] = useState(-1);
  const [lyricExpanded, setLyricExpanded] = useState(false);
  const lyricsContainerRef = useRef(null);


  const sources = [
    'netease','joox','tencent', 'tidal', 'spotify', 
    'ytmusic', 'qobuz',  'deezer',
    'migu', 'kugou', 'kuwo', 'ximalaya'
  ];

  const qualities = ['128', '192', '320', '740', '999'];

  const parseLyric = (text) => {
    const lines = text.split('\n');
    const pattern = /\[(\d+):(\d+\.\d+)\]/;
    
    return lines.map(line => {
      const match = line.match(pattern);
      if (match) {
        const minutes = parseFloat(match[1]);
        const seconds = parseFloat(match[2]);
        return {
          time: minutes * 60 + seconds,
          text: line.replace(match[0], '').trim()
        };
      }
      return null;
    }).filter(Boolean);
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query) return;

    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE}`, {
        params: {
          types: 'search',
          source: source,
          name: query,
          count: 20,
          pages: 1
        }
      });
      // setResults(response.data || []);
            // 获取结果后处理封面
        const resultsWithCover = await Promise.all(
          response.data.map(async track => ({
            ...track,
            picUrl: await fetchCover(track.source, track.pic_id)
          }))
        );
        
        setResults(resultsWithCover);
    } catch (error) {
      console.error('Search error:', error);
      toast.error('搜索失败，请稍后重试', {
        icon: '❌',
        className: 'custom-toast error-toast'
      });
    }
    setLoading(false);
  };

  
const fetchCover = async (source, picId, size = 300) => {
  const cacheKey = `${source}-${picId}-${size}`;
  
  // 检查缓存
  if (coverCache[cacheKey]) return coverCache[cacheKey];

  try {
    const response = await axios.get(`${API_BASE}`, {
      params: {
        types: 'pic',
        source: source,
        id: picId,
        size: size
      }
    });
    
    const url = response.data.url.replace(/\\/g, '');
    
    // 更新缓存
    setCoverCache(prev => ({
      ...prev,
      [cacheKey]: url
    }));
    
    return url;
  } catch (error) {
    console.error('封面获取失败:', error);
    return 'default_cover.jpg'; 
  }
};

  const handlePlay = async (track) => {
    if (currentTrack?.id === track.id) {
      setIsPlaying(!isPlaying);
      return;
    }

    try {
      const [urlResponse, lyricResponse] = await Promise.all([
        axios.get(API_BASE, {
          params: { types: 'url', source: track.source, id: track.id, br: quality }
        }),
        axios.get(API_BASE, {
          params: { types: 'lyric', source: track.source, id: track.lyric_id }
        })
      ]);
      console.log(urlResponse.data.size);
      
      
  
      const rawLyric = lyricResponse.data.lyric || '';
      const tLyric = lyricResponse.data.tlyric || '';
      
      setLyricData({
        rawLyric,
        tLyric,
        parsedLyric: parseLyric(rawLyric)
      });

      setPlayerUrl('');
      setIsPlaying(false);

      const response = await axios.get(`${API_BASE}`, {
        params: {
          types: 'url',
          source: track.source,
          id: track.id,
          br: quality
        }
      });

      const url = response.data?.url?.replace(/\\/g, '');
      if (!url) throw new Error('无效的音频链接');
  
      // 确保状态更新顺序
      setCurrentTrack(track);
      setPlayerUrl(url);
      setIsPlaying(true);

    } catch (error) {
      console.error('Play error:', error);
      setIsPlaying(false);
      setPlayerUrl('');
      toast.warning('当前音频无效不可用', {
        icon: '⚠️',
        className: 'custom-toast warning-toast'
      });
    }
  };

  const useThrottle = (callback, delay) => {
    const lastCall = useRef(0);
    
    return useCallback((...args) => {
      const now = new Date().getTime();
      if (now - lastCall.current >= delay) {
        lastCall.current = now;
        callback(...args);
      }
    }, [callback, delay]);
  };

  const handleProgress = useThrottle((state) => {
    const currentTime = state.playedSeconds;
    const lyrics = lyricData.parsedLyric;
    
    let newIndex = -1;
    for (let i = lyrics.length - 1; i >= 0; i--) {
      if (currentTime >= lyrics[i].time) {
        newIndex = i;
        break;
      }
    }
  
    if (newIndex !== currentLyricIndex) {
      setCurrentLyricIndex(newIndex);
    }
  }, 500); // 节流500m

  const handleDownload = async (track) => {
    try {
      const response = await axios.get(`${API_BASE}`, {
        params: {
          types: 'url',
          source: track.source,
          id: track.id,
          br: quality
        }
      });
      
      const downloadUrl = response.data.url.replace(/\\/g, '');
      const link = document.createElement('a');
      link.href = downloadUrl;
      // link.download = `${track.name} - ${track.artist}.mp3`; //下载为mp3格式
      const extension = getFileExtension(downloadUrl);
      link.download = `${track.name} - ${track.artist}.${extension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error) {
      console.error('Download error:', error);
      toast.error('下载失败，请稍后重试', {
        icon: '❌',
        className: 'custom-toast error-toast'
      });
    }
  };

  // 处理文件名后缀
  const getFileExtension = (url) => {
    try {
      // 处理可能包含反斜杠的URL
      const cleanUrl = url.replace(/\\/g, '');
      const fileName = new URL(cleanUrl).pathname
        .split('/')
        .pop()
        .split(/[#?]/)[0]; // 移除可能的哈希和查询参数
      
      // 使用正则表达式提取后缀
      const extensionMatch = fileName.match(/\.([a-z0-9]+)$/i);
      return extensionMatch ? extensionMatch[1] : 'audio';
    } catch {
      return 'audio'; // 默认后缀
    }
  };


// 添加滚动效果
useEffect(() => {
  if (lyricExpanded && currentLyricIndex >= 0 && lyricsContainerRef.current) {
    const activeLines = lyricsContainerRef.current.getElementsByClassName('active');
    if (activeLines.length > 0) {
      activeLines[0].scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: 'nearest'
      });
    }
  }
}, [currentLyricIndex, lyricExpanded]);


  return (
     <Container className="my-4"
     style={{ 
      paddingBottom: lyricExpanded ? '320px' : '120px',
      transition: 'padding 0.3s ease'
    }}
     >
      <Github/>
      <h1 className="text-center mb-4">全平台音乐搜索</h1>
      
      <Form onSubmit={handleSearch} className="mb-4">
        <Row className="g-2">
                   
          <Col md={5}>
            <Form.Control
              type="search"
              placeholder="输入歌曲名、歌手或专辑"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </Col>

          <Col md={3}>
            <Form.Select 
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              {sources.map(src => (
                <option key={src} value={src}>{src.toUpperCase()}</option>
              ))}
            </Form.Select>
          </Col>
          
          <Col md={2}>
            <Dropdown>
              <Dropdown.Toggle variant="outline-secondary">
                音质: {quality}k
              </Dropdown.Toggle>
              <Dropdown.Menu>
                {qualities.map(q => (
                  <Dropdown.Item key={q} onClick={() => setQuality(q)}>
                    {q}k
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown>
          </Col>
          
          <Col md={2}>
            <Button variant="primary" type="submit" className="w-100">
              搜索
            </Button>
          </Col>
        </Row>
      </Form>

      {loading && (
        <div className="text-center my-4">
          <Spinner animation="border" />
        </div>
      )}

      <Row className="g-4">
        {results.map((track) => (
          <Col key={track.id} md={6} lg={4}>
            <Card>
              <Card.Body>
                <div className="d-flex align-items-center">
                <img
                    src={track.picUrl || 'default_cover.jpg'}
                    alt="专辑封面"
                    className="me-3 rounded"
                    style={{ 
                      width: '60px', 
                      height: '60px',
                      objectFit: 'cover',
                      backgroundColor: '#f5f5f5' 
                    }}
                    onError={(e) => {
                      e.target.src = 'default_cover.png';
                    }}
                  />
                  <div>
                    <h6 className="mb-1">{track.name}</h6>
                    <small className="text-muted">{track.artist} - {track.album}</small>
                  </div>
                </div>
                
                <div className="mt-2 d-flex justify-content-end">
                <Button 
                  variant="outline-primary" 
                  size="sm"
                  style={{ marginRight: '0.1rem' }}
                  onClick={() => handlePlay(track)}
                  disabled={loading || (currentTrack?.id === track.id && !playerUrl)}
                >
                  {loading && currentTrack?.id === track.id ? (
                    <Spinner animation="border" size="sm" />
                  ) : currentTrack?.id === track.id ? (
                    isPlaying ? <FaPause /> : <FaPlay />
                  ) : (
                    <FaPlay />
                  )}
                </Button>
                  <Button 
                    variant="outline-success" 
                    size="sm"
                    onClick={() => handleDownload(track)}
                  >
                    <FaDownload />
                  </Button>
                </div>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>

      <div className="fixed-bottom bg-light p-3 border-top"
      style={{
        height: lyricExpanded ? '300px' : 'auto',
        boxShadow: '0 -2px 10px rgba(0,0,0,0.1)',
        zIndex: 1000
      }}
      >
        <Row className="align-items-center">
          <Col md={3}>
          <div className="d-flex ">
            {currentTrack && (
              <div className="d-flex align-items-center">
                <img 
                  src={coverCache[`${currentTrack.source}-${currentTrack.pic_id}-300`] || 'default_cover.png'}
                  alt="当前播放"
                  style={{ width: '50px', height: '50px' }}
                  className="me-2 rounded"
                />
                <div>
                  <h6 className="mb-0">{currentTrack.name}</h6>
                  <small className="text-muted">{currentTrack.artist}</small>
                </div>
              </div>
            )}
            <Button 
              variant="link"
              onClick={() => setLyricExpanded(!lyricExpanded)}
              className="ms-2"
              title={lyricExpanded ? '收起歌词' : '展开歌词'}
            >{lyricExpanded ? <FaChevronDown /> : <FaChevronUp />}
            </Button>
          </div>
          </Col>
          
      <Col md={6}>
      <div 
        className={`lyric-container ${lyricExpanded ? 'expanded' : 'collapsed'}`}
        style={{ 
          maxHeight: lyricExpanded ? '400px' : '60px',
          transition: 'max-height 0.3s ease' 
        }}
      >
        <div className="lyric-wrapper">
          
          {lyricData.parsedLyric[currentLyricIndex] && (
            <div className="current-lyric">
              {lyricData.parsedLyric[currentLyricIndex].text}
              {lyricData.tLyric && (
                <div className="translated-lyric">
                  {parseLyric(lyricData.tLyric)[currentLyricIndex]?.text}
                </div>
              )}
              
            </div>
          )}
          
          {lyricExpanded && (
            <div 
            className="full-lyrics" 
            ref={lyricsContainerRef}
            onScroll={(e) => {
              // 记录用户滚动行为
              sessionStorage.setItem('userScrolled', true);
            }}
            >
            {lyricData.parsedLyric.map((line, index) => (
              <div
                key={index}
                className={`lyric-line ${index === currentLyricIndex ? 'active' : ''}`}
                data-time={line.time}
              >
                  <div>{line.text}</div>
                  {lyricData.tLyric && (
                    <div className="translated-lyric">
                      {parseLyric(lyricData.tLyric)[index]?.text}
                    </div>
                  )}
                </div>
              ))}
              {lyricData.parsedLyric.length === 0 && (
                <div className="text-center text-muted py-3">暂无歌词</div>
              )}
                </div>
         )}
         {lyricData.parsedLyric.length === 0 && (
                <div className="current-lyric">暂无歌词</div>
         )}

          
        </div>
      </div>
      <ReactPlayer
            ref={playerRef}
            onProgress={handleProgress}
            url={playerUrl}
            playing={isPlaying}
            onReady={() => console.log('播放器就绪')}
            onError={(e) => {
              console.error('播放错误:', e);
              setIsPlaying(false);
            }}
            onEnded={() => {
              setIsPlaying(false);
              // 保留当前曲目信息但停止播放
            }}
            config={{ file: { forceAudio: true } }}
            height={0}
            style={{ display: playerUrl ? 'block' : 'none' }} // 隐藏未初始化的播放器
          />
       </Col>
          
          <Col md={3} className="text-end">
          <Button
            variant="link"
            onClick={() => setIsPlaying(!isPlaying)}
            disabled={!currentTrack || !playerUrl}
          >
            {!currentTrack ? (
              <FaMusic size={24} className="text-muted" />
            ) : isPlaying ? (
              <FaPause size={24} />
            ) : (
              <FaPlay size={24} />
            )}
          </Button>
          </Col>
        </Row>
      </div>
    </Container>
  );
};

export default MusicSearch;