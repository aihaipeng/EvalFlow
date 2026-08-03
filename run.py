"""Agent Bench Web 服务入口。"""

from copy import copy
import logging

import uvicorn
from uvicorn.logging import AccessFormatter, ColourizedFormatter, ansi_style


class LevelLogFormatter(ColourizedFormatter):
    """通用日志：级别紧贴内容并按级别着色。"""

    def formatMessage(self, record):
        recordcopy = copy(record)
        levelname = recordcopy.levelname
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
        recordcopy.__dict__["levelprefix"] = levelname + ":"
        # 直接 %-format，跳过 ColourizedFormatter.formatMessage 对 levelprefix 的填充覆盖
        return logging.Formatter.formatMessage(self, recordcopy)


class AccessLogFormatter(AccessFormatter):
    """访问日志：级别紧贴内容并按级别着色，请求行省略 HTTP 版本。"""

    def formatMessage(self, record):
        recordcopy = copy(record)
        (
            client_addr,
            method,
            full_path,
            _http_version,
            status_code,
        ) = recordcopy.args
        status_code = self.get_status_code(int(status_code))
        request_line = f"{method} {full_path}"
        if self.use_colors:
            request_line = ansi_style(request_line, bold=True)
        levelname = recordcopy.levelname
        if self.use_colors:
            levelname = self.color_level_name(levelname, recordcopy.levelno)
        recordcopy.__dict__.update(
            {
                "client_addr": client_addr,
                "request_line": request_line,
                "status_code": status_code,
                "levelprefix": levelname + ":",
            }
        )
        # 跳过 AccessFormatter.formatMessage（会重建带 HTTP 版本的 request_line 和带填充的 levelprefix），
        # 直接 %-format，避免 ColourizedFormatter 覆盖 levelprefix。
        return logging.Formatter.formatMessage(self, recordcopy)


_ACCESS_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "run.LevelLogFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "access": {
            "()": "run.AccessLogFormatter",
            "fmt": '%(levelprefix)s%(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}


def main() -> None:
    """启动 Agent Bench Web 服务。"""
    uvicorn.run(
        "web.app:app",
        host="127.0.0.1",
        port=8010,
        reload=True,
        log_config=_ACCESS_LOG_CONFIG,
    )


if __name__ == "__main__":
    main()
