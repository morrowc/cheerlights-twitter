#!/usr/bin/python
"""Search Twitter for a hashtag, parse colors from the data and change lights.

Inspired by the Cheerlights project, do not require a full wired conenction.


"""

import httplib
import json
import logging
import Queue
import socket
import sys
import time
import urllib

import serial
import twitter

from optparse import OptionParser
from threading import Thread

LOGFILE = '/tmp/cheerlights.log'

color_queue = Queue.Queue()

author = 'christopher.morrow@gmail.com'


def RetrieveAccess(f):
  """Eval the contents of a config file.

  Args:
    f: a string, the filename of the config file.
  Returns:
    a dict of (consumer_key, consumer_secret, access_key, access_secret)
  """
  tags = ('consumer_key', 'consumer_secret', 'access_key', 'access_secret')
  t = {}
  try:
    fd = open(f)
  except IOError:
    print 'Failed to open the access file: %s' % f

  for line in fd.readlines():
    line = line.rstrip()
    (tag, val) = line.split('=')
    if tag in tags:
      t[tag] = val

  return t


class Lights(Thread):
  """Watch a queue, send the inbound updates to the xbee interface.

  Args:
    xbee: a Serial interface.
    color_queue: a Queue.Queue object to watch for colors to change.
    report: a string, the URL to report the color change to.
  """
  def __init__(self, xbee, queue, report, debug=False):
    self.color_queue = queue
    self.counter = 0
    self.debug = debug
    self.report = report
    self.xbee = xbee
    Thread.__init__(self)

  def reportchange(self, color):
    """Send a report request to the web collector.
    """
    if not self.report:
      return

    try:
      report = urllib.urlopen(self.report % color)
    except IOError, e:
      logging.debug('Failed to update the web collector: %s', e)
      return

    if report.read() != 'ok\n':
      logging.debug('Failed to update the color on the web colletor: %s',
                    color)

  def run(self):
    """Run a loop, reading from a queue and writing to the serial obj.
    """
    while True:
      logging.info('Starting through the color reading loop.')
      color = self.color_queue.get()
      logging.info('LIGHTS Sending color: %s to the xbee.', color.upper())
      if not self.debug:
        self.xbee.write(' %s ' % str(color))
      else:
        print '[DEBUG]: Color written to xbee: %s' % color
      self.counter += 1
      self.reportchange(str(color))
      logging.info('LIGHTS wrote %d colors to the lights so far.',
          self.counter)
      time.sleep(2)


class TagCrawler(object):
  """Crawl twitter search API for matches to specified tag.  Use since_id to
  hopefully not submit the same message twice.  However, bug reports indicate
  since_id is not always reliable, and so we probably want to de-dup ourselves
  at some level.

  Args:
    xbee: a filehandle, the xbee serial interface as a file descriptor.
    queue: a Queue.Queue object, to write colors to.
    tag: a string, the search term to look for at twitter.
    interval: an integer, how often to re-search.
    max_id: an integer, the last twitter result id seen.
    debug: a boolean, to output debug information or not.
    con_key: a string, the consumer access key for twitter API calls.
    con_secret: a string, the consumer access secret for twitter API cals.
    access_key: a string, the access_key for the application API at twitter.
    access_secret: a string, the access_secret for the application API at
    twitter.
  """

  def __init__(self, xbee, queue, tag=None, interval=10,
      max_id=None, debug=False, con_key=None, con_secret=None,
      access_key=None, access_secret=None):
    self.access_key = access_key
    self.access_secret = access_secret
    self.api = None
    self.colors = set(['red', 'green', 'blue', 'cyan', 'magenta', 'orange',
                         'yellow', 'white', 'purple', 'black', 'pink'])
    self.color_queue = queue
    self.consumer_key = con_key
    self.consumer_secret = con_secret
    self.debug = debug
    self.interval = interval
    self.max_id = max_id
    self.tag = tag
    self.xbee = xbee
      
  def search(self):
    """Search twitter for the tagline.

    Returns:
      a list, of text from each twitter json object.
    """
    result = []
    try:
      response = self.api.GetSearch(count=10, term=self.tag,
                                    max_id = self.max_id)
    except urllib2.URLError as e:
      logging.info('Failed to GetSearch -> Tag: %s. Id: %s Err: %s',
          self.tag, self.max_id, e)
      return result

    try:
      if len(response) > 1:
        logging.debug('Resetting max-id from: %s to %s.',
            self.max_id, response[-1].id)
        self.max_id = response[-1].id
    except urllib2.URLError as e:
      logging.info('Failed to get a response length: %s', e)
      return result

    for resp in response:
      result.append(resp.text)

    print 'Returning from search with %s responses.' % len(result)  
    print 'Maxid: %s' % self.max_id

    return result

  def loop(self):
    """Loop waiting for a search result, passing that along to submit.

    Raises:
      AttributeError: if the twitter api create fails.
    """
    try:
      api = twitter.Api(
          consumer_key=self.consumer_key,
          consumer_secret=self.consumer_secret,
          access_token_key=self.access_key,
          access_token_secret=self.access_secret,
          )
    except AttributeError as e:
      logging.error('Failed to generate a new twitter-api handle: %s', e)
      raise

    logging.info('Created api handle for twitter api.')
    self.api = api

    while True:
      logging.info("COLLECTOR Starting search")
      print 'Starting search'
      data = self.search()
      if data:
        logging.info("COLLECTOR %d new result(s)", len(data))
        print '[DEBUG] %d new results()' % len(data)
        self.submit(data)
      else:
        logging.info("COLLECTOR No new results")
        print 'No new results'
        print 'sleeping for %s seconds' % self.interval
        logging.info("COLLECTOR Search complete sleeping for %d seconds",
            self.interval)
      time.sleep(float(self.interval))

  def submit(self, data):
    """Read the string output from each search attempt's output.

    Put a color onto the Queue.Queue if one is found in the string.
    Args:
      data: a list of strings.
    """
    for item in data:
      print 'Colors loop text: "%s"' % item
      print ('  found colors:'),
      for word in item.split():
        if word.lower() in self.colors:
          logging.info('COLLECTOR wrote %s to the queue.', word)
          print (' %s' % word),
          self.color_queue.put(word)

      print '.'


def main():
  """Handle options, start the xbee writer and the search loop.
  """
  opts = OptionParser()
  opts.add_option('-a', '--access_conf', dest='access_conf',
                  default=None,
                  help='Configuration file of access token data. eval() able.')
  opts.add_option('-b', '--baud', dest='baud', default=9600,
                  help='Baud rate for the serial interface.')

  opts.add_option('-i', '--interval', dest='interval', default=10,
                  help='How often to poll the Twitter service.')

  opts.add_option('-s', '--serial', dest='serial', default='/dev/ttyUSB0',
                  help='A serial interface to open for writing.')

  opts.add_option('-t', '--tag', dest='tag', default='#cheerlights',
                  help='Twitter tag to search/follow.')

  opts.add_option('-r', '--report', dest='report',
                  default='http://cheerlightsdata.appspot.com/?color=%s',
                  help='A full URL with substitution for the color.')

  opts.add_option('-d', '--debug', dest='debug',
                  default=None,
                  help='Debug run, do not write to serial interface.\n'
                  'Logs sent to %s' % LOGFILE)

  (options, unused_args) = opts.parse_args()

  logging.basicConfig(filename=LOGFILE, level=logging.DEBUG)

  if not options.access_conf:
    print 'Failed to provide access credantials, please do so.'
    sys.exit(1)

  access_toks = RetrieveAccess(options.access_conf)

  if not options.debug:
    xbee = serial.Serial(options.serial, options.baud)
  else:
    xbee = open(LOGFILE, 'rw')
  if options.debug or xbee.isOpen():
    # Create the color writing thread
    color_thread = Lights(xbee, color_queue, options.report, options.debug)
    color_thread.setDaemon(True)
    color_thread.start()

    crawl = TagCrawler(xbee, color_queue,
                       options.tag, int(options.interval),
                       debug=options.debug,
                       con_key=access_toks['consumer_key'],
                       con_secret=access_toks['consumer_secret'],
                       access_key=access_toks['access_key'],
                       access_secret=access_toks['access_secret'],
                       )
    crawl.loop()


if __name__ == '__main__':
  main()
