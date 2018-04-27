#!/usr/bin/env python
import gspread
from oauth2client.service_account import ServiceAccountCredentials

ballroom = "BallroomA"

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name('self-video-zach-208096653289.json', scope)
gc = gspread.authorize(credentials)
gdspreadsheet = gc.open("speakers-list")
worksheet = gdspreadsheet.worksheet(ballroom)



def start():
	updatepos()
	updateneg()
	updateneutral()
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