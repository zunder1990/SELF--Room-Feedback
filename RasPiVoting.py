#!/usr/bin/env pythoni
from ast import literal_eval
import csv
import collections
from copy import deepcopy
import gspread
import logging
import json
from oauth2client.service_account import ServiceAccountCredentials
# import RPi.GPIO as GPIO            # Uncomment when on Pi
import random
import time
import subprocess
from datetime import datetime, timedelta
import sys
import os
import multiprocessing 
import Queue

CONFIG_FILE = 'config.json'
CREDENTIALS_FILE = 'self-video-zach-208096653289.json'
LOCAL_SCHEDULE_CACHE_FILE = 'schedule_cache.json'  # Used as fallback schedule if google sheet won't validate
LOCAL_GSHEET_PAGE_CACHE = 'gsheet_page_cache.json' # A Copy of the state of the google sheets event page 
SCOPE = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

# Define how the Google sheet is set up
SHEET_NAME = 'speakers-list'
SHEET_COL_HDG_EVENT_ID = 'TalkID'
SHEET_COL_HDG_EVENT_ROOM = 'Room'
SHEET_COL_HDG_EVENT_DATE = 'Date'
SHEET_COL_HDG_EVENT_TIME = 'startTime'
SHEET_COL_POS_VOTE = 'H'
SHEET_COL_NEG_VOTE = 'I'
SHEET_COL_NEUTRAL_VOTE = 'J'

POSITIVE_VOTE = 'Positive'
NEGATIVE_VOTE = 'Negative'
NEUTRAL_VOTE = 'Neutral'

POSITIVE_PIN = 19   # Zach to verify
NEGATIVE_PIN = 13   # Zach to verify
NEUTRAL_PIN = 6     # Zach to verify

SESSION_MIN = 90    # Zach to verify - 90 min sessions
BREAK_MIN = 15      # Zach to verify - 15 min breaks between

Event = collections.namedtuple('Event', 'id room start_datetime end_datetime')

vote_options = [POSITIVE_VOTE, NEGATIVE_VOTE, NEUTRAL_VOTE]

class FeedbackCollector:
	'''FeedbackCollector handles collection of GPIO events and sending them to queue.

	Args: 
		queue: Multiprocessing queue where output is placed.

	Attributes:
		config (dict): Configuration parameters loaded from external config file.
		credentials: Google account credentials as created from external credentials file.
		currentEvent: Current event id being logged.
		gc: Google connection created using credentials
		gsheet: The Google Sheet being used
		worksheet: The page (sheet/tab within the gsheet) being used.

	'''

	@staticmethod
	def getConfig(filename):
		'''Reads the local config file (json format) from file system

		Args:
			filename: Filename of external json file with configuration.

		Returns:
			dict representation of the json config file.	
		'''
		with open(filename) as f:
			return json.load(f)

	def buildSchedule(self, logger):
		'''Builds/Updates the Event Schedule for this particular device based on the room from
		the device config.

		Args:
			none

		Returns:
			(list of Event tuples) Current room schedule
		'''
		gSchedule = self.gsheet.worksheet(self.config['room_id']).get_all_records()

		# save a local copy of the worksheet to filesystem.
		# Mainly, just so somebody has all the event information locally if needed after the event.
		with open(LOCAL_GSHEET_PAGE_CACHE, 'w') as f_out:
			json.dump(gSchedule, f_out)

		# Build a schedule from the appropriate Google Sheets page data.
		schedule = []
		for row in gSchedule:
			# Convert date, time to real datetime objects for the start and end of the 
			# events.
			dt_string = '{0}-2018 {1}'.format(
				row[SHEET_COL_HDG_EVENT_DATE], 
				row[SHEET_COL_HDG_EVENT_TIME])
			start_datetime = datetime.strptime(dt_string, '%m-%d-%Y %H:%M') 
			end_datetime = start_datetime + timedelta(seconds=(60 * (SESSION_MIN + BREAK_MIN)))

			event = Event(id=row[SHEET_COL_HDG_EVENT_ID], 
				room=row[SHEET_COL_HDG_EVENT_ROOM], 
				start_datetime=start_datetime,
				end_datetime=end_datetime)

			logger.debug('''Adding event to schedule: id {0} in {1} start: {2} end: {3}'''
				.format(event.id, event.room, event.start_datetime, event.end_datetime))
			schedule.append(event)

		return schedule

	def getSchedule(self):
		return self.roomSchedule

	def validateSchedule(self, logger):
		'''Sanity checks on room schedule / list of events

		A list of room events is expected to be non-zero and no 2 events should
		exist for same date and time.

		Note: Validation fails/passes silently. Only logs the details.

		Args:
			s: (list) Room scheduled event list
			logger: (logger) The logger to write results to
		'''
		cnt = len(self.roomSchedule)
		if(cnt):
			logger.debug('Validating {0} events in room\'s schedule.'.format(cnt))
			for i in xrange(0, cnt-1):
				e1 = self.roomSchedule[i]  # The event being validated in the schedule
				for j in xrange(i+1, cnt):
					e2 = self.roomSchedule[j] # Some other event in the schedule
					
					if e1.start_datetime == e2.start_datetime:
						logger.degug('''Event schedule FAILS VAILIDATION. Duplicate 
							date or time found in schedule.''')
		else:
			logger.debug('Event schedule is empty.')

		logger.info('Successfully validated {0} events for roomID: \'{1}\' schedule.'
			.format(cnt, self.config['room_id']))

	def votePositive(self):
		'''
		GPIO callback function for positive vote button press
		'''
		record = {}
		record['Vote'] = POSITIVE_VOTE
		record['Timestamp'] = datetime.now()

		# Add the record to the multiprocessing queue for the feedback writer
		self.queue.put(record)
		self.logger.info("VOTE record added to queue: {0}".format(record))

	def voteNegative(self):
		'''
		GPIO callback function for negative vote button press
		'''
		record = {}
		record['Vote'] = NEGATIVE_VOTE
		record['Timestamp'] = datetime.now()

		# Add the record to the multiprocessing queue for the feedback writer
		self.queue.put(record)
		self.logger.info("VOTE record added to queue: {0}".format(record))

	def voteNeutral(self):
		'''
		GPIO callback function for negative vote button press
		'''
		record = {}
		record['Vote'] = NEUTRAL_VOTE
		record['Timestamp'] = datetime.now()

		# Add the record to the multiprocessing queue for the feedback writer
		self.queue.put(record)
		self.logger.info("VOTE record added to queue: {0}".format(record))

	def simulateVoting(self):
		'''
		Hacky way to simulate voting if not hooked up on Pi with GPIO
		'''
		while(True):
			time.sleep(1)
			vote = random.choice(vote_options)
			self.logger.info('SIMULATING: {0} vote.'.format(vote))

			# call the GPIO callback directly
			if vote == POSITIVE_VOTE:
				self.votePositive()
			elif vote == NEGATIVE_VOTE:
				self.voteNegative()
			else:
				self.voteNeutral()

	def __init__(self, queue, logger):
		'''Instantiate new FeedbackCollector Object

		Args:
			queue: Multiprocessing queue object to be loaded with collected feedback.
			logger: logging object from main - probably not best way to do this, but it works.
		'''
		self.config = self.getConfig(CONFIG_FILE)
		self.credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
		self.gc = gspread.authorize(self.credentials)
		self.gsheet = self.gc.open(SHEET_NAME)
		#self.worksheet = self.gsheet.worksheet(self.config['room_id'])
		self.queue = queue
		self.logger = logger

		self.roomSchedule = self.buildSchedule(logger)

		# Results of schedule validation will be written to log only
		self.validateSchedule(logger)
	
	def __repr__(self):
		# Overly verbose __repr__ because we may be headless and relying on log for debug
		myRepr = "FeatureCollector Object \n"
		myRepr += " .config = {0}\n".format(self.config)
		myRepr += " .gsheet = {0}\n".format(self.gsheet)
		#myRepr += " .worksheet = {0}\n".format(self.worksheet)
		myRepr += " .roomSchedule = {0}\n".format(self.roomSchedule)

		return myRepr

class FeedbackWriter:
	'''FeebackWriter object is responsible for updating vote tallies and writing to 
	local file and Google Sheets.
	'''
	
	@staticmethod
	def getConfig(filename):
		'''Reads the local config file (json format) from file system

		Args:
			filename: Filename of external json file with configuration.

		Returns:
			dict representation of the json config file.	
		'''
		with open(filename) as f:
			return json.load(f)

	def getEventID(self, timestamp):
		event_id = 'None'
		for event in self.schedule:
			if timestamp >= event.start_datetime \
			    and timestamp <= event.end_datetime:

				event_id = event.id

		self.logger.info("getEventID() found event: {0} for timestamp {1}".format(
			event_id, timestamp))

		return event_id  # TODO:  Implent logic

	def writeFeedback(self):
		self.logger.info('FeedbackWriter.writeFeedback() loop started')
		rows = []
		base_time = datetime.now()
		while True:
			feedback_list = []
			time.sleep(5) # Do processing once every 5 seconds - No need to go wide open.

			while self.queue.qsize() != 0:
				feedback_list.append(self.queue.get())
			
			if feedback_list.count == 0:
				continue   # Short circuit loop if no feedback
			
			self.logger.info('FeedbackWriter read feedback from queue:\n{0}'.format(feedback_list))

			# Write (append) to local daily vote log
			with open(self.feedbackLogFile, 'a+') as f_out:
				writer = csv.writer(f_out, delimiter=',')
				for r in feedback_list:	
					# Need to get the event / lookup
					event_id = self.getEventID(r['Timestamp'])
					
					if event_id == 'None':
						continue

					row =[r['Timestamp'], event_id, r['Vote']]
					writer.writerow(row)

					#self.worksheet.insert_row(row, 2)  # Busts Google API request limit quickly
					# Attempt to batch rows to update every 3 minutes to protect API limit
					rows.append(row)
			
			# Every 2 minutes, re-tally and send updated counts to Google Spreadsheet
			cur_time = datetime.now()
			delta = (cur_time - base_time)
			if delta.seconds >= int(self.config['update_gsheet_seconds']):
				self.logger.info("!--> Feedback Writer - Tally for Google Sheet update.")
				base_time = cur_time # reset timer

				# Make copy of initial tallys
				init_tallies = deepcopy(self.tally_dict)
				self.logger.info("Initial Tallies: {0}".format(str(init_tallies)))

				# Add new votes to existing tally
				with open(self.feedbackLogFile, 'r') as f_in:
					reader = csv.reader(f_in, delimiter=',')
					for row in reader:
						event_id = row[1]
						# Update the event tally counters
						# Vote is index 2 in csv file currently
						if(row[2] == POSITIVE_VOTE):
							self.tally_dict[event_id]['positive'] += 1
						elif(row[2] == NEGATIVE_VOTE):
							self.tally_dict[event_id]['negative'] += 1
						elif(row[2] == NEUTRAL_VOTE):
							self.tally_dict[event_id]['neutral'] += 1

				self.logger.info("Current Tallies: {0}".format(str(self.tally_dict)))

				# update the google sheet anywhere the tally has changed
				for key, value in self.tally_dict.iteritems():
					self.logger.info('Key: {0}, Value: {1}, init_tally: {2}'.format(
						key, str(value), str(init_tallies[key])))
					
					if value['positive'] != init_tallies[key]['positive'] or \
						value['negative'] != init_tallies[key]['negative'] or \
						value['neutral'] != init_tallies[key]['neutral']:
						self.logger.info('Need to update Google Sheet for event: {0}'.format(key))
						# The current tally has changed from initial tally
						# get row in google sheet to adjust
						cell = self.worksheet.find(key)
						target = '{0}{1}'.format(SHEET_COL_POS_VOTE, str(cell.row))
						self.worksheet.update_acell(target, str(value['positive']))
						target = '{0}{1}'.format(SHEET_COL_NEG_VOTE, str(cell.row))
						self.worksheet.update_acell(target, str(value['negative']))
						target = '{0}{1}'.format(SHEET_COL_NEUTRAL_VOTE, str(cell.row))
						self.worksheet.update_acell(target, str(value['neutral']))						

	def __init__(self, queue, logger, schedule):
		'''Instantiate new FeedbackWriter Object

		Args:
			queue: Multiprocessing queue object that we need to write the feedback from.
			logger: logging object from main - probably a better way to do this, but it works.
		'''
		self.config = self.getConfig(CONFIG_FILE)
		self.credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
		self.gc = gspread.authorize(self.credentials)
		self.gsheet = self.gc.open(SHEET_NAME)
		self.worksheet = self.gsheet.worksheet(self.config['room_id'])
		self.queue = queue
		self.logger = logger
		self.schedule = schedule
		self.tally_dict = {}

		# Initialize tally dictionary element for every event
		for event in schedule:
			self.tally_dict[event.id] = {'positive': 0, 'negative': 0, 'neutral': 0}

		# Log file for each day - will be appended to throughout.
		currenttime = datetime.now().strftime('%m_%d')
		self.feedbackLogFile = "%s_feedback.csv" % str(currenttime)
		
		# see if the day's feedback log file exists, if not - create now and add heading row
		if not os.path.exists(self.feedbackLogFile):
			with open(self.feedbackLogFile, 'w') as f_out:
				writer = csv.writer(f_out, delimiter=',')
				writer.writerow(['Timestamp', 'EventID', 'Feedback'])
				

	def __repr__(self):
		# Overly verbose __repr__ because we may be headless and relying on log for debug
		myRepr = "FeedbackWriter Object \n"
		myRepr += " .config = {0}\n".format(self.config)
		myRepr += " .gsheet = {0}\n".format(self.gsheet)
		myRepr += " .worksheet = {0}\n".format(self.worksheet)
		myRepr += " .feedbackLogFile = {0}\n".format(self.feedbackLogFile)

		return myRepr

#def start(fc, logger):
	#stop_writing  = updater()
	#GPIO.setmode(GPIO.BCM)

	#GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	#GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	#GPIO.setup(6, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	#try: input()
	#except KeyboardInterrupt: sys.exit()
	#finally:
		#stop_writing.set()
		#GPIO.output(6,GPIO.LOW)
		#GPIO.output(13,GPIO.LOW)
		#GPIO.output(18,GPIO.LOW)
	#vote = "pos"
	#updater(vote)	

def googlesheetlookup():
	currenttime = datetime.now().strftime('%m-%d-%H:%M')
	cell = worksheet.find(currenttime)

	talkID = worksheet.acell("""A""" + str(cell.row) + """ """).value
	print "Talk ID = ", talkID
	updater(talkID)

'''
Zach's original functions - commented out for now. VS 2018.05.20

def updatepos(talkID):
	cell = worksheet.find(talkID)
	value = worksheet.acell("""I""" + str(cell.row) + """ """).value
	newvalue = int(value) + 1
	worksheet.update_acell("""I""" + str(cell.row) + """ """, """ """ + str(newvalue) + """ """)

def updateneg():

	cell = worksheet.find(talkID)
	value = worksheet.acell("""G""" + str(cell.row) + """ """).value
	newvalue = int(value) + 1
	worksheet.update_acell("""G""" + str(cell.row) + """ """, """ """ + str(newvalue) + """ """)
	
def updateneutral():

	cell = worksheet.find(talkID)
	value = worksheet.acell("""H""" + str(cell.row) + """ """).value
	newvalue = int(value) + 1
	worksheet.update_acell("""H""" + str(cell.row) + """ """, """ """ + str(newvalue) + """ """)
'''


def main():
	# Set up for a file log, since this will be headless
	logging.basicConfig(level=logging.DEBUG,
		format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%m-%d %H:%M',
        filename='debug.log',
        filemode='w')
	logger = logging.getLogger('main')
	logger.info('START FeedbackCollector script')

	# Set up Multiprocessing queue to share
	queue = multiprocessing.Queue()

	# Instantiate our collector
	collector = FeedbackCollector(queue, logger)
	logger.info('FeedbackCollector object instantiated.')
	logger.debug('FeedbackCollector: %s' % str(collector)) #Instantiate our writer
	writer = FeedbackWriter(queue, logger, collector.getSchedule())
	logger.info('FeedbackWriter object instantiated.')

	# Zach - SETUP GPIO HERE
	# GPIO.setup(POSITIVE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	# GPIO.setup(NEGATIVE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	# GPIO.setup(NEUTRAL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

	# May need glitch filter here

	# Add our callback function to GPIO pin event interrupts
	# GPIO.add_event_detect(POSITIVE_PIN, GPIO.FALLING, callback = writer.votePositive)
	# GPIO.add_event_detect(NEGATIVE_PIN, GPIO.FALLING, callback = writer.voteNegative)
	# GPIO.add_event_detect(NEUTRAL_PIN, GPIO.FALLING, callback = writer.voteNeutral)

	# ! THIS SECTION CAN STAY COMMENTED OUT FOR NOW !! #
	# Pretty certain that using callbacks now there is no need to have a dedicated collector
	# process
	# collectorProcess = multiprocessing.Process(target=collector.collectFeedback)
	# collectorProcess.start()

	# Start the writer
	writerProcess = multiprocessing.Process(target=writer.writeFeedback)
	writerProcess.start()

	# Start simulating votes if needed
	if collector.config['simulate_voting'] in ['True', 'TRUE', 'true']:
		simulatorProcess = multiprocessing.Process(target=collector.simulateVoting)
		simulatorProcess.start()

	# Don't stop the main process until child process finish, which should be never.	
	# collectorProcess.join()
	if simulatorProcess:
		simulatorProcess.join()
	writerProcess.join()

if __name__ == "__main__":
	main()



