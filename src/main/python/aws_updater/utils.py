from functools import wraps
from time import time
import logging


def timed(function):

    @wraps(function)
    def wrapper(*args, **kwds):
        start = time()
        result = function(*args, **kwds)
        elapsed = time() - start
        print "{0} took {1} s to finish".format(function.__name__, elapsed)
        return result

    return wrapper


def get_logger():
    logging.basicConfig(format='%(asctime)s %(levelname)s %(module)s: %(message)s',
                        datefmt='%d.%m.%Y %H:%M:%S',
                        level=logging.INFO)
    return logging.getLogger(__name__)