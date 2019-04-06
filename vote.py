import RPi.GPIO as GPIO
import time
import paho.mqtt.client as mqtt
#
POSITIVE_PIN = 19
NEGATIVE_PIN = 13
NEUTRAL_PIN = 26
#
Ballroom="A"
#
mqttbroker="192.168.1.60"
mqttport=1883


GPIO.setmode(GPIO.BCM)

GPIO.setup(POSITIVE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(NEGATIVE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(NEUTRAL_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

client = mqtt.Client("P1") #create new instance
client.connect(mqttbroker,keepalive=20) #connect to broker


while True:
	input_statePOSITIVE_PIN = GPIO.input(POSITIVE_PIN)
	input_stateNEGATIVE_PIN = GPIO.input(NEGATIVE_PIN)
	input_stateNEUTRAL_PIN = GPIO.input(NEUTRAL_PIN)
	if input_statePOSITIVE_PIN == False:
		print('POSITIVE_PIN Button  Pressed')
		client.publish("vote/" + Ballroom + "","POSITIVE_PIN")#publish
		time.sleep(1)
	if input_stateNEGATIVE_PIN == False:
		print('NEGATIVE_PIN Button Pressed')
		client.publish("vote/" + Ballroom + "","NEGATIVE_PIN")#publish
		time.sleep(1)
	if input_stateNEUTRAL_PIN == False:
		print('NEUTRAL_PIN Button Pressed')
		client.publish("vote/" + Ballroom + "","NEUTRAL_PIN")#publish
		time.sleep(1)

		
		
