const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function(app) {
  app.use(
    '/api',
    createProxyMiddleware({
      target: 'https://music-api.gdstudio.xyz/api.php',
      changeOrigin: true,
      pathRewrite: {
        '^/api': '', // 把 "/api" 从路径中移除
      },
    })
  );
};