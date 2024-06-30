#!/bin/sh
if [ ! -p /tmp/msgchannel ];
then
mkfifo /tmp/msgchannel /tmp/msgincoming /tmp/msg_plain /tmp/msg_input
fi
exit 0

