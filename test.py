

import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s  %(name)s    %(levelname)s   %(message)s {%(filename)s:%(funcName)s:%(lineno)d}')
from epd17299 import *

with Epd17299() as disp:
    disp.clear()
