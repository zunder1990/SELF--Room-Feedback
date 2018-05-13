#!/usr/bin/env pythoni
from ast import literal_eval
import csv
import collections
import gspread
import logging
import json
from oauth2client.service_account import ServiceAccountCredentials
#import RPi.GPIO as GPIO
import random
import time
import subprocess
from datetime import datetime
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
SHEET_COL_HDG_EVENT_ID = 'EventID'
SHEET_COL_HDG_EVENT_ROOM = 'Room'
SHEET_COL_HDG_EVENT_DATE = 'Date'
SHEET_COL_HDG_EVENT_TIME = 'startTime'

PIN_18_FEEDBACK = 'Positive'
PIN_13_FEEDBACK = 'Negative'
PIN_6_FEEDBACK = 'Neutral'

Event = collections.namedtuple('Event', 'id room date time')
vote_options = [PIN_18_FEEDBACK, PIN_13_FEEDBACK, PIN_6_FEEDBACK]

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
		gSchedule = self.gsheet.worksheet(self.config['schedule_sheet']).get_all_records()

		# save a local copy of the worksheet to filesystem.
		# Mainly, just so somebody has all the event information locally if needed after the event.
		with open(LOCAL_GSHEET_PAGE_CACHE, 'w') as f_out:
			json.dump(gSchedule, f_out)

		schedule = []
		for row in gSchedule:
			event = Event(id=row[SHEET_COL_HDG_EVENT_ID], 
				room=row[SHEET_COL_HDG_EVENT_ROOM], 
				date=row[SHEET_COL_HDG_EVENT_DATE], 
				time=row[SHEET_COL_HDG_EVENT_TIME])
			if( event.room == self.config['room_id']):
				# Found event that matches with this device's configuration, add to schedule
				logger.debug('''Adding event to schedule: id {0} in {1} on {2} @ {3}'''
					.format(event.id, event.room, event.date, event.time))
				schedule.append(event)

		return schedule

	def validateSchedule(self, logger):
		'''Sanity checks on room schedule / list of events

		A list of room events is expected to be non-zero and no 2 events should
		exist for same date and time.

		Note: Validation fails/passes silently. Only logs the details.

		Note 2: In the event of failed validation of Google Sheet schedule, 
		will attempt to load schedule from schedule_cache.json in local filesystem.

		Args:
			s: (list) Room scheduled event list
			logger: (logger) The logger to write results to
		'''
		cnt = len(self.roomSchedule)
		loadFromCache = False
		if(cnt):
			logger.debug('Validating {0} events in room\'s schedule.'.format(cnt))
			for i in xrange(0, cnt-1):
				e1 = self.roomSchedule[i]  # The event being validated in the schedule
				for j in xrange(i+1, cnt):
					e2 = self.roomSchedule[j] # Some other event in the schedule
					
					if e1.date == e2.date and e1.time == e2.time:
						logger.degug('''Event schedule FAILS VAILIDATION. Duplicate 
							date or time found in schedule.''')
						loadFromCache = True
		else:
			logger.debug('Event schedule is empty.')
			loadFromCache = True

		if not loadFromCache:	
			logger.info('Successfully validated {0} events for roomID: \'{1}\' schedule.'
				.format(cnt, self.config['room_id']))

			# Had successful validation, update any cached copy with this one.	
			logger.debug('Caching copy of validated schedule to local filesystem.')
			schedule = {}
			schedule['configuration'] = self.config
			event_ids, rooms, dates, times = [], [], [], []
			for i in range(len(self.roomSchedule)):
				event_ids.append(self.roomSchedule[i].id)
				rooms.append(self.roomSchedule[i].room)
				dates.append(self.roomSchedule[i].date)
				times.append(self.roomSchedule[i].time)
			events = [{SHEET_COL_HDG_EVENT_ID: i, SHEET_COL_HDG_EVENT_ROOM: r,
				SHEET_COL_HDG_EVENT_DATE: d, SHEET_COL_HDG_EVENT_TIME:t} for i,r,d,t in 
				zip(event_ids, rooms, dates, times)]
			schedule['events'] = json.dumps(literal_eval(str(events)))
			with open(LOCAL_SCHEDULE_CACHE_FILE, 'w') as f_out:
				json.dump(schedule, f_out)
			return
		
		# If here, need to try to read cached copy of schedule from file system
		# Assumes that any schedule that got saved previously must have passed
		# validation to get there in the first place.
		logger.debug("Updating roomSchedule with cached schedule from file system.")	
		logger.debug("(local schedule_cache.json assumed to be good.)")
		with open(LOCAL_SCHEDULE_CACHE_FILE, 'r') as f_in:
				self.roomSchedule = json.load(f_in)
				# TODO: This could still stand additional robustness, but think it 
				# is good enough for now.

	def collectFeedback(self):
		'''Perform the feedback collection activity.

		Note: Once started, loops infinitely doing the following:
		 * Based on current time, decide what event we are logging
		 * Listen for GPIO / Button input
		 * When button press is detected, write a new vote to the queue.
		'''
		self.logger.info('FeedbackCollector.collectFeedback() loop started.')
		base_datetime = datetime.now()
		while True:
			cur_datetime = datetime.now()
			record = {}

			if self.config['simulate_voting'] in ['True', 'TRUE']:
				# Simulate Feedback as crude testing
				delta = (cur_datetime - base_datetime)
				if delta.seconds >= 3:
					# Simulator will make a random vote every 3 seconds
					# Update start_datetime to current time
					base_datetime = cur_datetime
					vote = random.choice(vote_options)
					record[SHEET_COL_HDG_EVENT_ROOM] = self.config['room_id']
					record['Timestamp'] = str(cur_datetime)
					record['Vote'] = vote

					# Add the record to the multiprocessing queue for the feedback writer
					self.logger.info("SIMULATION: collected feedback record: \n{0}".format(record))
					self.queue.put(record)
					self.logger.info("SIMULATION: wrote feedback record to queue.")
				
				continue # the infinite main loop here if we are simulating votes

			# if here, we are not simulating data - GPIO input actually happening				

			#input_state18 = GPIO.input(18)
			#input_state13 = GPIO.input(13)
			#input_state6 = GPIO.input(6)
			input_state18 = True;
			input_state13 = False;
			input_state6 = False;
			vote = 'None'
			if input_state18 == False:
				vote = vote_options[0]  # Positive feedback
			elif input_state13 == False:
				vote = vote_options[1]  # Negative feedback
			elif input_state6 == False:
				vote = vote_options[2]  # Neutral feedback

			if vote != 'None':
				record[SHEET_COL_HDG_EVENT_ROOM] = self.config['room_id']
				record['Timestamp'] = str(cur_datetime)
				record['Vote'] = vote

				# Add the record to the multiprocessing queue for the feedback writer
				self.logger.info("FEEDBACK ACQUIRED: collected feedback record: \n{0}".format(record))
				self.queue.put(record)
				self.logger.info("FEEDBACK ACQUIRED: wrote feedback record to queue.")

			time.sleep(1) #seconds  ( 1 seems too long for "live" device, experiment if needed )


			# Lookup what event in schedule

			# Collect feedback here


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


	def writeFeedback(self):
		self.logger.info('FeedbackWriter.writeFeedback() loop started')
		rows = []
		base_time = datetime.now()
		while True:
			feedback_list = []
			time.sleep(5) # Do processing once every 5 seconds - No need to go wide open.

			while self.queue.qsize() != 0:
				feedback_list.append(self.queue.get())
			
			self.logger.info('FeedbackWriter read feedback from queue:\n{0}'.format(feedback_list))

			# Write (append) to local daily vote log
			with open(self.feedbackLogFile, 'a+') as f_out:
				writer = csv.writer(f_out, delimiter=',')
				for r in feedback_list:	
					# Need to get the event / lookup
					row =[r['Timestamp'], 'EventFoo', r['Room'], r['Vote']]
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
				count_pos = 0
				count_neg = 0
				count_neutral = 0
				with open(self.feedbackLogFile, 'r') as f_in:
					reader = csv.reader(f_in, delimiter=',')
					for row in reader:
						# Vote is index 3 in csv file currently
						if(row[3] == PIN_18_FEEDBACK ):
							count_pos += 1
						elif(row[3] == PIN_13_FEEDBACK):
							count_neg += 1
						elif(row[3] == PIN_6_FEEDBACK):
							count_neutral += 1
				sheet_row = [str(cur_time), count_pos, count_neg, count_neutral]
				self.worksheet.append_row(sheet_row, 2)


	def __init__(self, queue, logger):
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

		# Log file for each day - will be appended to throughout.
		currenttime = datetime.now().strftime('%m_%d')
		self.feedbackLogFile = "%s_feedback.csv" % str(currenttime)
		
		# see if the day's feedback log file exists, if not - create now and add heading row
		if not os.path.exists(self.feedbackLogFile):
			with open(self.feedbackLogFile, 'w') as f_out:
				writer = csv.writer(f_out, delimiter=',')
				writer.writerow(['Timestamp', 'EventID', 'Room', 'Feedback'])
				

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

def input():
	while True:
		#input_state18 = GPIO.input(18)
		#input_state13 = GPIO.input(13)
		#input_state6 = GPIO.input(6)
		input_state18 = True;
		input_state13 = False;
		input_state6 = False;
		if input_state18 == False:
			vote = "pos"
		if input_state13 == False:
			vote = "neg"
		if input_state6 == False:
			vote = "neutral"
		queue.put(vote)
		time.sleep(1)#seconds
	
def updater():
	def update(stop):
		while not stop.is_set():
			try:
				for _ in range(0, queue.qsize()):
					vote = queue.get_nowait()
					if vote is "pos":
							updatepos()
					if vote is "neg":
							updateneg()
					if vote is "neutral":
							updateneutral()
					time.sleep(1) # seconds
			except Queue.Empty: pass
			except KeyboardInterrupt: pass
	stop = multiprocessing.Event()
	multiprocessing.Process(target=update, args=[stop]).start()
	return stop


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

if __name__ == "__main__":
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
	logger.debug('FeedbackCollector: %s' % str(collector))

	#Instantiate our writer
	writer = FeedbackWriter(queue, logger)
	logger.info('FeedbackWriter object instantiated.')

	collectorProcess = multiprocessing.Process(target=collector.collectFeedback)
	collectorProcess.start()
	writerProcess = multiprocessing.Process(target=writer.writeFeedback)
	writerProcess.start()


	collectorProcess.join()
	writerProcess.join()

