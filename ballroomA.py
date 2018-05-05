#!/usr/bin/env python
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
#import RPi.GPIO as GPIO
import time
import subprocess
from datetime import datetime
import sys
import os
import multiprocessing
import Queue

CONFIG_FILE = 'config.json'
CREDENTIALS_FILE = 'self-video-zach-208096653289.json'
SCOPE = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
SHEET_NAME = 'speakers-list'

class FeedbackCollector:

	'''
	getConfig()

	Reads the local config file (json format) from file system
	'''
	@staticmethod
	def getConfig(filename):
		with open(filename) as f:
			return json.load(f)

	def __init__(self):
		self.config = self.getConfig(CONFIG_FILE)
		self.credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
		self.gc = gspread.authorize(self.credentials)
		self.gsheet = self.gc.open(SHEET_NAME)
		self.worksheet = self.gsheet.worksheet(self.config['room_id'])
		self.queue = multiprocessing.Queue()

		print self.config
		print self.worksheet



def start():
	stop_writing  = updater()
	#GPIO.setmode(GPIO.BCM)

	#GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	#GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	#GPIO.setup(6, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	try: input()
	except KeyboardInterrupt: sys.exit()
	finally:
		stop_writing.set()
		#GPIO.output(6,GPIO.LOW)
		#GPIO.output(13,GPIO.LOW)
		#GPIO.output(18,GPIO.LOW)
	#vote = "pos"
	#updater(vote)

def checklist():
		currenttime = datetime.now().strftime('%m-%d-%H:%M')
		print "time now = ", currenttime
		if currenttime in starttimes:
			print "current time in list = ", currenttime
			googlesheetlookup() 
			exit
	

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
	collector = FeedbackCollector()
	start()