"""
Flask App 工厂
静态文件服务 + API + 操作日志
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

STATIC_DIR = Path(__file__).parent / "static"


def create_app():
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='')
    app.config['JSON_AS_ASCII'] = False
    app.config['JSON_SORT_KEYS'] = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── 注册 Blueprint ─────────────────────────────────────────
    from src.web.routes.stock import stock_bp, etf_bp, fund_bp
    from src.web.routes.trade import trade_bp
    from src.web.routes.portfolio import portfolio_bp
    from src.web.routes.ai import ai_bp, chat_bp
    from src.web.routes.backtest import backtest_bp
    from src.web.routes.news import news_bp
    from src.web.routes.system import system_bp
    from src.web.routes.logs import logs_bp
    from src.web.routes.mock_trade import mock_trade_bp
    from src.web.routes.console import console_bp
    from src.web.routes.real_trade import real_trade_bp
    from src.web.routes.strategy import strategy_bp
    from src.web.routes.train import train_bp

    app.register_blueprint(stock_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(fund_bp)
    app.register_blueprint(trade_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(backtest_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(mock_trade_bp)
    app.register_blueprint(console_bp)
    app.register_blueprint(console_bp, url_prefix='/api/console', name='console_alias')
    app.register_blueprint(real_trade_bp)
    app.register_blueprint(strategy_bp)
    app.register_blueprint(train_bp)

    # ── 操作日志钩子 ───────────────────────────────────────────
    from src.utils.operation_logger import before_request_handler, after_request_handler, log_system

    _req_start = {}

    @app.before_request
    def _before():
        _req_start[id(request)] = time.time()

    @app.after_request
    def _after(response):
        try:
            start = _req_start.pop(id(request), None)
            if start is None:
                return response
            duration_ms = (time.time() - start) * 1000
            path = request.path
            if path.startswith(('/js/', '/css/', '/favicon', '/static/')):
                return response
            from src.utils.operation_logger import log_api
            log_api(
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                ip=request.remote_addr or '',
            )
        except Exception:
            pass
        return response

    # ── 错误处理 ───────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        # API 请求返回 JSON
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Not found'}), 404
        # 其他请求 fallback 到 index.html（SPA 模式）
        return send_from_directory(str(STATIC_DIR), 'index.html')

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

    # ── 根路由 → Dashboard ─────────────────────────────────────
    @app.route('/')
    def index():
        return send_from_directory(str(STATIC_DIR), 'index.html')

    # ── API 根路由（兼容旧前端） ───────────────────────────────
    @app.route('/api')
    def api_root():
        return jsonify({
            'success': True,
            'name': 'QuantPro API',
            'version': '5.0',
            'modules': {
                'stock': '/api/stock/*',
                'etf': '/api/etf/*',
                'trade': '/api/trade/*',
                'real_trade': '/api/real_trade/*',
                'mock': '/api/mock/*',
                'portfolio': '/api/portfolio/*',
                'ai': '/api/ai/*',
                'chat': '/api/chat/*',
                'backtest': '/api/backtest/*',
                'news': '/api/news/*',
                'system': '/api/system/*',
                'logs': '/api/logs/*',
                'console': '/api/console/*',
                'strategy': '/api/strategy/*',
            }
        })

    # 记录启动
    try:
        log_system('startup', f'Flask app created')
    except Exception:
        pass

    return app


if __name__ == '__main__':
    from config.settings import server_config
    app = create_app()
    app.run(host=server_config.host, port=server_config.port, debug=server_config.debug)
