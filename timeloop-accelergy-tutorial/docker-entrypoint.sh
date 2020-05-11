#!/bin/sh


# Set UID/GID if not provided with enviromental variable(s).
if [ -z "$USER_UID" ]; then
	USER_UID=$(cat /etc/passwd | grep tutorial | cut -d: -f3)
	echo "USER_UID variable not specified, defaulting to tutorial user id ($USER_UID)"
fi

if [ -z "$USER_GID" ]; then
	USER_GID=$(cat /etc/group | grep tutorial | cut -d: -f3)
	echo "USER_GID variable not specified, defaulting to tutorial user group id ($USER_GID)"
fi

# Look for existing group, if not found create group "tutorial" with specified GID.
FIND_GROUP=$(grep ":$USER_GID:" /etc/group)

if [ -z "$FIND_GROUP" ]; then
	usermod -g users tutorial
	groupdel tutorial
	groupadd -g $USER_GID tutorial
fi

# Set "tutorial" account's UID.
usermod -u $USER_UID -g $USER_GID --non-unique tutorial > /dev/null 2>&1

# Populate "tutorial" directory, and
# change ownership of files in "tutorial" home
if [ ! -d /home/tutorial/exercises ]
then
   cp -r /usr/local/src/timeloop-accelergy-exercises/exercises /home/tutorial
   chown -R $USER_UID:$USER_GID /home/tutorial/exercises
fi

# Change owner/permissions on "tutorial" home folder
chown $USER_UID:$USER_GID /home/tutorial
chmod 755 /home/tutorial

if [ ! -e /home/tutorial/.nointro ]
then
    more /home/tutorial/exercises/README.md
fi

# Default environment variable for Timeloop
export TIMELOOP_ACCURATE_READS_WITU=1

#if [ "$#" -eq 0 ] || [ "${1#-}" != "$1" ]
if [ "$@" != "bash" ] 
then
    echo "Command: >>> $@ <<<"
    exec "$@"
fi

exec su tutorial -s "/bin/bash" # -c "$@"
