#!/usr/bin/env python3
#
# meshpipe-server - piping meshmail messages to/from FIFO over meshtastic radio.
#
# Copyright (c) Resilience Theatre, 2024
# Copyright (c) 2021, datagod
# 
# FIFO files:
#
# /tmp/meshmail_in -> meshtastic radio
# /tmp/meshmail_out <- meshtastic radio
#
# Run:
#
# python3 meshpipe.py --port=[usb_serial_device]
#
# This work is based on:
#
#  https://github.com/datagod/meshwatch/
#  See LICENSE.meshwatch
#

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
import time
import traceback
import argparse
import collections
import sys
import os
import stat, os
import math
import inspect
import subprocess
import select
from meshtastic.mesh_pb2 import _HARDWAREMODEL
from meshtastic.node import Node
from pubsub import pub
from signal import signal, SIGINT
from sys import exit
from datetime import datetime
import os, tempfile

NAME = 'meshpipe-server'                   
DESCRIPTION = "FIFO pipe meshmail messages from Meshtastic devices"
DEBUG = False

parser = argparse.ArgumentParser(description=DESCRIPTION)
parser.add_argument('-p', '--port', type=str, help="meshtastic port (eg. /dev/ttyACM0)")
ifparser = parser.add_mutually_exclusive_group(required=False)
ifparser.add_argument('-i', '--host', type=str, help="hostname/ipaddr of the device to connect to over TCP")
args = parser.parse_args()



global Interface
global DeviceStatus
global DeviceName
global DevicePort
global PacketsReceived
global PacketsSent
global LastPacketType
global BaseLat
global BaseLon
global MacAddress
global DeviceID

def ErrorHandler(ErrorMessage,TraceMessage,AdditionalInfo):
  CallingFunction =  inspect.stack()[1][3]
  print("Error - Function (",CallingFunction, ") has encountered an error. ")
  print(ErrorMessage)
  print("Trace")
  print(TraceMessage)
  if (AdditionalInfo != ""):
    print("Additonal info:",AdditionalInfo)
  sys.exit()

#
# meshtastic
#
def DecodePacket(PacketParent,Packet):
  global DeviceStatus
  global DeviceName
  global DevicePort
  global PacketsReceived
  global PacketsSent
  global LastPacketType
  global HardwareModel
  global DeviceID 
  
  print('\n--- decodepacket ---')
  
  if isinstance(Packet, collections.abc.Mapping):

    for Key in Packet.keys():
      Value = Packet.get(Key) 
      if isinstance(Value, collections.abc.Mapping):
        LastPacketType = Key.upper()
        DecodePacket("{}/{}".format(PacketParent,Key).upper(),Value)  
      else:
        if(Key == 'raw'):
            pass
        else:
          if not isinstance(Value, bytes):
            print("{: <20} {: <20}".format(Key,Value))

  else:
      print('Warning: Not a packet!\n')
  

#
# Packet receive with 'From' handling
#
def onReceive(packet, interface): 
    global PacketsReceived
    global PacketsSent
    global fifo_write
    PacketsReceived = PacketsReceived + 1
    Decoded  = packet.get('decoded')
    Message  = Decoded.get('text')
    To       = packet.get('to')
    From     = packet.get('from')

    DecodePacket('MainPacket',packet)

    if(Message):
        print('Incoming message:')
        # Hex with leading zero (TODO: Check 'server address' write) 
        hexFrom=f"{From:08X}"
        print("From: {: <20}".format(hexFrom)) 
        print("{: <20} {: <20}".format(hexFrom,Message))
        incomingMessage = str(hexFrom) + "|" + Message + '\n' # 2->1
        fifo_write = open('/tmp/meshmail_out', 'w')
        fifo_write.write(incomingMessage)
        fifo_write.flush()


def onConnectionEstablished(interface, topic=pub.AUTO_TOPIC): 

    # TODO: Do we need this? 
    From = "BaseStation"
    To   = "All"
    current_time = datetime.now().strftime("%H:%M:%S")
    Message = "meshpipe-server active [{}]".format(current_time)
    print("From: {} - {}".format(From,Message,To))

    try:
      interface.sendText(Message, wantAck=False)
      print("== Packet SENT==")
      print("To:      {}:".format(To))
      print("From:    {}:".format(From))
      print("Message: {}:".format(Message))

    except Exception as ErrorMessage:
      TraceMessage = traceback.format_exc()
      AdditionalInfo = "Sending text message ({})".format(Message)
      ErrorHandler(ErrorMessage,TraceMessage,AdditionalInfo)


def onConnectionLost(interface, topic=pub.AUTO_TOPIC): 
  print('onConnectionLost \n')

def onNodeUpdated(interface, topic=pub.AUTO_TOPIC): 
  print('onNodeUpdated \n')
   

def SIGINT_handler(signal_received, frame):
  print('SIGINT detected. \n')
  sys.exit()


#
# Send message functions
# https://github.com/meshtastic/python/blob/18c2d08bf0ef5c17bf10e6e0d2bde00221bda0e9/meshtastic/mesh_interface.py#L279
# destinationId
#
#
def send_msg(interface, Message):
    interface.sendText(Message, wantAck=True)
    print("== Packet SENT ==")
    print("To:      All:")
    print("From:    BaseStation")
    print('Message: {}'.format(Message))
    print('')

def send_msg_from_fifo(interface, Message):
    outMsg = Message + '\n'
    interface.sendText(outMsg, wantAck=True)
    print("== FIFO Packet SENT ==")
    print("To:      All:")
    print("From:    BaseStation")
    print('Message: {}'.format(Message))
    print('')

def send_msg_from_fifo_to_one_node(interface, Message, nodeId):
    outMsg = Message + '\n'
    interface.sendText(outMsg, wantAck=True,destinationId=nodeId)
    print("== FIFO Packet to one node SENT ==")
    print("To:      {}".format(nodeId))
    print("From:    BaseStation")
    print('Message: {}'.format(Message))
    print('')



def GetMyNodeInfo(interface):

    Distance   = 0
    DeviceName = ''
    BaseLat    = 0
    BaseLon    = 0
    TheNode = interface.getMyNodeInfo()
    DecodePacket('MYNODE',TheNode)

    print("\n--GetMyNodeInfo--")

    if 'latitude' in TheNode['position'] and 'longitude' in TheNode['position']:
      BaseLat = TheNode['position']['latitude']
      BaseLon = TheNode['position']['longitude']
      print('** GPS Location: ', BaseLat,BaseLon)

    if 'longName' in TheNode['user']:
      print('Long name: ', TheNode['user']['longName'])

    if 'hwModel' in TheNode['user']:
      print('HW model:  ',TheNode['user']['hwModel'])
    
    if 'macaddr' in TheNode['user']:
      print('Mac addr.  ', TheNode['user']['macaddr'])

    if 'id' in TheNode['user']:
      print('User ID:   ',TheNode['user']['id'])
      server_address=TheNode['user']['id']
      # Store server address for 'meshmail' to read it
      print('Writing server address:   ',server_address)
      f = open("/tmp/serveraddress", "w")
      f.write(server_address[1:])
      f.close()

    if 'batteryLevel' in TheNode['position']:
      print('Battery:   ',TheNode['position']['batteryLevel'])

    print('---\n')


def deg2num(lat_deg, lon_deg, zoom):
  lat_rad = math.radians(lat_deg)
  n = 2.0 ** zoom
  xtile = int((lon_deg + 180.0) / 360.0 * n)
  ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
  return (xtile, ytile)
      
# TODO: Deliver nodes to fifo or create mesh status fifo for UI?
def DisplayNodes(interface):
    
    print('\n-- DisplayNodes --')

    try:
      for node in (interface.nodes.values()):
        print("NAME:      {}".format(node['user']['longName']))  
        print("NODE:      {}".format(node['num']))  
        print("ID:        {}".format(node['user']['id']))  
        print("MAC:       {}".format(node['user']['macaddr']))
        if 'position' in node.keys():
          #used to calculate XY for tile servers
          if 'latitude' in node['position'] and 'longitude' in node['position']:
            Lat = node['position']['latitude']
            Lon = node['position']['longitude']
            xtile,ytile = deg2num(Lat,Lon,10)
            print("Tile: {}/{}".format(xtile,ytile)) 
            print("LAT:  {}".format(node['position']['latitude']))  
            print("LONG: {}".format(node['position']['longitude']))

          if 'batteryLevel' in node['position']:
            Battery = node['position']['batteryLevel']
            print("Battery:   {}".format(Battery))  
        
        if 'lastHeard' in node.keys():
          LastHeardDatetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(node['lastHeard']))
          print("LastHeard: {}".format(LastHeardDatetime))  

        print('-----')


    except Exception as ErrorMessage:
      TraceMessage = traceback.format_exc()
      AdditionalInfo = "Processing node info"
      ErrorHandler(ErrorMessage,TraceMessage,AdditionalInfo)


def create_fifo_pipe(pipe_path):
    try:
        os.mkfifo(pipe_path)
        print(f"Named pipe created at {pipe_path}")
    except OSError as e:
        print(f"Error: {e}")


#
# main 
#
def main():
  global interface
  global DeviceStatus
  global DeviceName
  global DevicePort
  global PacketsSent
  global PacketsReceived
  global LastPacketType
  global HardwareModel
  global MacAddress
  global DeviceID
  global HardwareModel
  global BaseLat
  global BaseLon

  try:

    DeviceName      = '??'
    DeviceStatus    = '??'
    DevicePort      = '??'
    PacketsReceived = 0
    PacketsSent     = 0
    LastPacketType  = ''
    HardwareModel   = ''
    MacAddress      = ''
    DeviceName      = ''
    DeviceID        = ''
    HardwareModel   = '??'
    BaseLat         = 0
    BaseLon         = 0

    # Check fifo files
    fifo_file='/tmp/meshmail_out'
    if not os.path.exists(fifo_file):
        print('Missing fifo file: ',fifo_file)
        create_fifo_pipe(fifo_file)
    
    fifo_file='/tmp/meshmail_in'
    if not os.path.exists(fifo_file):
        print('Missing fifo file: ',fifo_file)
        create_fifo_pipe(fifo_file)
    
    if (args.host):
      print("Connecting to device on host {}".format(args.host))
      interface = meshtastic.tcp_interface.TCPInterface(args.host)
    elif (args.port):
      print("Connecting to device at port {}".format(args.port))
      interface = meshtastic.serial_interface.SerialInterface(args.port)

    # Get node info for connected device
    GetMyNodeInfo(interface)

    # subscribe to connection and receive channels
    pub.subscribe(onConnectionEstablished, "meshtastic.connection.established")
    pub.subscribe(onConnectionLost,        "meshtastic.connection.lost")
    pub.subscribe(onReceive, "meshtastic.receive")

    # Display nodes
    DisplayNodes(interface)

    # Open FIFO for reading
    FIFO = '/tmp/meshmail_in'

    # Main loop, reads fifo in and sends data over meshtastic
    fifo_read=open(FIFO,'r')

    while True:
      time.sleep(2)
      fifo_msg_in = fifo_read.readline()[:-1]
      if not fifo_msg_in == "":
        print('FIFO Message in: ', fifo_msg_in)
        # New method where we parse 'to' and deliver answer only to originating node (who sent 'server')
        answer_array=fifo_msg_in.split("|")
        # Evaluate array len
        array_len = len(answer_array)
        # Send as broadcast by default on Edgemap UI
        if array_len == 2:
            send_msg_from_fifo(interface, fifo_msg_in)
        # Send to individual recipient
        if array_len == 3:
            answer_recipient = '!'+answer_array[0]
            answer_payload = answer_array[1]+"|"+answer_array[2]
            send_msg_from_fifo_to_one_node(interface, answer_payload, answer_recipient)
        
      else:
        # No fifo data
        pass

    interface.close()  

  except Exception as ErrorMessage:
    time.sleep(2)
    TraceMessage = traceback.format_exc()
    AdditionalInfo = "Main function "
    ErrorHandler(ErrorMessage,TraceMessage,AdditionalInfo)

  signal(SIGINT, SIGINT_handler)


if __name__=='__main__':
  try:
      main()

  except Exception as ErrorMessage:
      TraceMessage = traceback.format_exc()
      AdditionalInfo = "Main pre-amble"
      ErrorHandler(ErrorMessage,TraceMessage,AdditionalInfo)

# %%

