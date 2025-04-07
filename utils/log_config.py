import logging
import logging.config

# Or from a dictionary
def setup_logging():
    config_dict = {
        'version': 1,
        'formatters': {
            'standard': {
                'format': '%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s'
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'standard'
            },
            'file': {
                'class': 'logging.FileHandler',
                'filename': 'app.log',
                'level': 'DEBUG',
                'formatter': 'standard'
            }
        },
        'loggers': {
            '': {  # Root logger
                'handlers': ['console', 'file'],
                'level': 'DEBUG',
                'propagate': True
            }
        }
    }
    logging.config.dictConfig(config_dict)