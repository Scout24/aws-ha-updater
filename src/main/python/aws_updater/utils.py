from functools import wraps
from time import time


def timed(function):

    @wraps(function)
    def wrapper(*args, **kwds):
        start = time()
        result = function(*args, **kwds)
        elapsed = time() - start
        print "{0} took {1} s to finish".format(function.__name__, elapsed)
        return result

    return wrapper