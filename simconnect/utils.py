import inspect, os, logging, logging.config, sys

_loggers = {} # name --> _Logger instance
class _Logger:
    '''simple wrapper around logging.Logger to make it more convenient: you can still use
    methods like debug and error and info, but you can pass in multiple args instead of building
    the string yourself. You can also call the object directly to trigger a call to .info.
    Simplest use case is to put this near the top of your module:
    from utils import *
    log, logTB = Logger()
    '''
    def __init__(self, context):
        self.logger = logging.getLogger(context)

    def _msg(self, args):
        try:
            return ' '.join(str(x) for x in args)
        except UnicodeEncodeError:
            return 'ENCERR:' + repr(args)
    def debug(self, *args): self.logger.debug(self._msg(args))
    def info(self, *args): self.logger.info(self._msg(args))
    def warning(self, *args): self.logger.warning(self._msg(args))
    def error(self, *args): self.logger.error(self._msg(args))
    def critical(self, *args): self.logger.critical(self._msg(args))
    __call__ = info
    def tb(self): self.logger.error('', exc_info=1)

def Logger(context=None):
    '''creates (if needed) and returns (log, logTB) functions for the given context, which
    can be anything. If not supplied, it defaults to the caller's module filename.'''
    if context is None:
        context = os.path.basename(inspect.stack()[1].filename).split('.')[0]
    logger = _loggers.get(context)
    if logger is None:
        _loggers[context] = logger = _Logger(context)
    return logger, logger.tb
log, logTB = Logger() # global defaults

def InitLogging(logFilename, level=logging.INFO):
    logging.config.dictConfig(dict(
        version=1,
        disable_existing_loggers=False,
        formatters=dict(
            default=dict(
                format='[%(asctime)s %(name)14s] %(message)s',
                datefmt='%Y%m%d %H:%M:%S',
            ),
        ),
        handlers=dict(
            console={
                'class':'logging.StreamHandler',
                'formatter':'default',
                'stream': sys.stdout,
            },
            file={
                'class':'logging.FileHandler',
                'filename':logFilename,
                'encoding': 'utf8',
                'formatter':'default',
            },
        ),
        root=dict(level=level, handlers=['console', 'file']),
    ))
