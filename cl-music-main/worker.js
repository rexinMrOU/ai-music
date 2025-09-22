/**
 * Cloudflare Worker for Reverse Proxying music-api.gdstudio.xyz
 * with CORS headers and path rewriting (/api -> /api.php).
 */

// 目标 API 的基础 URL
const TARGET_API_BASE = 'https://music-api.gdstudio.xyz';
// 需要重写的源路径
const SOURCE_PATH = '/api';
// 重写后的目标路径
const TARGET_PATH = '/api.php';

export default {
  async fetch(request, env, ctx) {
    // --- 1. 构建目标 URL (包含路径重写) ---
    const url = new URL(request.url);
    let targetPath = url.pathname; // 默认使用原始路径

    // 检查路径是否需要重写
    if (url.pathname === SOURCE_PATH) {
      targetPath = TARGET_PATH; // 将 /api 替换为 /api.php
      console.log(`Path rewritten: ${url.pathname} -> ${targetPath}`); // Optional: logging for debugging
    }
    // --- 注意: 如果你只想允许 /api 路径，可以在这里添加 else 块 ---
    else {
      // 对于非 /api 的路径，返回 404 Not Found
      return new Response('Not Found. Only /api is allowed.', { status: 404 });
    }
    // -------------------------------------------------------------

    // 将目标 API 的域名/协议与（可能重写后的）路径和查询参数组合起来
    const targetUrl = new URL(targetPath + url.search, TARGET_API_BASE);
    console.log(`Forwarding request to: ${targetUrl.toString()}`); // Optional: logging

    // --- 2. 处理 CORS 预检请求 (OPTIONS) ---
    if (request.method === 'OPTIONS') {
      // 特别注意：如果只允许 /api，OPTIONS 请求也应该只在该路径下成功
      // 但通常 OPTIONS 是针对将要发生的实际请求路径，所以这里的处理保持不变即可
      return handleCorsPreflight(request);
    }

    // --- 3. 准备转发给目标 API 的请求 ---
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set('Host', new URL(TARGET_API_BASE).host);
    // 移除 Cloudflare 特定的头信息
    requestHeaders.delete('cf-connecting-ip');
    requestHeaders.delete('cf-ipcountry');
    requestHeaders.delete('cf-ray');
    requestHeaders.delete('cf-visitor');
    requestHeaders.delete('x-forwarded-proto');
    requestHeaders.delete('x-real-ip');

    // --- 4. 向目标 API 发送请求 ---
    let response;
    try {
      response = await fetch(targetUrl.toString(), {
        method: request.method,
        headers: requestHeaders,
        body: request.body,
        redirect: 'follow'
      });
    } catch (error) {
      console.error('Error fetching target API:', error);
      return new Response('Proxy failed to fetch target API', { status: 502 });
    }

    // --- 5. 准备返回给客户端的响应 (添加 CORS 头) ---
    const responseHeaders = new Headers(response.headers);
    responseHeaders.set('Access-Control-Allow-Origin', '*');
    responseHeaders.append('Vary', 'Origin');
    // 移除可能暴露信息的头
    responseHeaders.delete('X-Powered-By');
    responseHeaders.delete('server');

    // --- 6. 返回最终响应 ---
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders
    });
  }
};

/**
 * 处理 CORS 预检请求 (OPTIONS) 的辅助函数
 * @param {Request} request 传入的 OPTIONS 请求
 * @returns {Response} 带有 CORS 允许头的响应
 */
function handleCorsPreflight(request) {
  const headers = new Headers();
  const requestHeaders = request.headers;

  headers.set('Access-Control-Allow-Origin', '*'); // 或者指定你的域名
  headers.set('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, HEAD, OPTIONS');

  const requestedHeaders = requestHeaders.get('Access-Control-Request-Headers');
  if (requestedHeaders) {
    headers.set('Access-Control-Allow-Headers', requestedHeaders);
  } else {
    headers.set('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, X-Requested-With');
  }

  // headers.set('Access-Control-Allow-Credentials', 'true'); // 如果需要凭证且源非'*'
  headers.set('Access-Control-Max-Age', '86400'); // 24 小时

  return new Response(null, {
    status: 204, // No Content
    headers: headers
  });
}