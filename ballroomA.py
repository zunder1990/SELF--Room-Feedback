#!/usr/bin/env python
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import RPi.GPIO as GPIO
import time
import subprocess
from datetime import datetime
import sys
import os



ballroom = "BallroomA"

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name('self-video-zach-208096653289.json', scope)
gc = gspread.authorize(credentials)
gdspreadsheet = gc.open("speakers-list")
worksheet = gdspreadsheet.worksheet(ballroom)

queue = multiprocessing.Queue()

def start():
	stop_writing  = updater()
	GPIO.setmode(GPIO.BCM)

	GPIO.setup(18, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	GPIO.setup(13, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	GPIO.setup(6, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	try: input()
	except KeyboardInterrupt: sys.exit()
    finally:
        stop_writing.set()
		GPIO.output(6,GPIO.LOW)
		GPIO.output(13,GPIO.LOW)
		GPIO.output(18,GPIO.LOW)
	#vote = "pos"
	#updater(vote)

def input():
	var = 1
	while var == 1
		while True:	
			input_state18 = GPIO.input(18)
			input_state13 = GPIO.input(13)
			input_state6 = GPIO.input(6)
			if input_state18 == False:
				vote = "pos"
			if input_state13 == False:
				vote = "neg"
			if input_state6 == False:
				vote = "neutral"				
			queue.put(vote)
			time.sleep(1)#seconds
	except KeyboardInterrupt: sys.exit()
	
def updater():
	def update(stop)
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
					
def updatepos():
	value = worksheet.acell('I2').value
	newvalue = int(value) + 1
	worksheet.update_acell('I2', '' + str(newvalue) + '')
def updateneg():
	value = worksheet.acell('G2').value
	newvalue = int(value) + 1
	worksheet.update_acell('G2', '' + str(newvalue) + '')

def updateneutral():
	value = worksheet.acell('H2').value
	newvalue = int(value) + 1
	worksheet.update_acell('H2', '' + str(newvalue) + '')




start()