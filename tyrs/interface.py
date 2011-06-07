# -*- coding: utf-8 -*-
'''
@module    interface
@author    Nicolas Paris <nicolas.caen@gmail.com>
@license   GPLv3
'''

import re
import os
import sys
import tyrs
import time
import signal                   # resize event
import curses
import curses.wrapper

class Interface:
    ''' All dispositions in the screen, and some logics for display tweet

    self.status:  It's use mainly for display purpose
        current:    the current tweet highlight, from the statuses list
        first:      first status displayed, from the status list, mean if we display the midle
                    of the list, the first won't be 0
        last:       the last tweet from statuses list
    self.count            Keep the count of each statuses list
    self.api              The tweetter API (not directly the api, but the instance of Tweets in tweets.py)
    self.conf             The configuration file parsed in config.py
    self.maxyx            Array contain the window size [y, x]
    self.screen           Main screen (curse)
    self.last_read        keep the ID of the status for each lists of statuses
    self.unread           keep the count of tweet that haven't been read in other buffer, usefull to see active buffer
    self.statuses         4 lists for each buffer containing all status in each list, the name of each list
                          is the name of the buffer
    self.current_y        Current line in the screen
    self.resize_event     boleen if the window is resize
    self.regexRetweet     regex for retweet
    self.flash            [msg, type_msg]
                          Use like "session-flash", to display some information/warning messages
    self.refresh_token    Boleen to make sure we don't refresh timeline. Usefull to keep editing box on top
    self.buffer           The current buffer we're looking at, (home, mentions, direct search)
    self.timelines        List of available timelines
    '''

    status           = {'current': 0, 'first': 0, 'last': 0}
    statuses         = {}
    count            = {}
    unread           = {}
    last_read        = {}
    resize_event     = False
    regex_retweet     = re.compile('^RT @\w+:')
    flash = []
    refresh_token    = False
    buffer           = 'home'

    def __init__(self):
        '''
        @param api: instance of Tweets, will handle retrieve, sending tweets
        @param conf: contain all configuration parameters parsed
        '''
        self.api    = tyrs.container['api']
        self.conf   = tyrs.container['conf']
        self.api.set_ui(self)
        # resize event
        signal.signal(signal.SIGWINCH, self.sigwinch_handler)
        # startup the ncurses mode
        self.init_screen()
        # initialize statuses, count, unread...
        self.init_dict()
        # first update of home timeline
        self.update_timeline('home')
        self.display_timeline()

    def init_screen(self):

        screen = curses.initscr()
        curses.noecho()         # Dont print anything
        curses.cbreak()
        screen.keypad(1)        # Use of arrow keys
        curses.curs_set(0)      # Dont display cursor
        curses.meta(1)          # allow 8bits inputs
        self.init_colors()
        self.maxyx = screen.getmaxyx()
        screen.border()

        screen.refresh()
        self.screen = screen

    def init_colors(self):
        '''Setup all colors stuff, rgb as well.'''
        curses.start_color()

        if self.conf.params['transparency']:
            curses.use_default_colors()
            bgcolor = -1
        else:
            bgcolor = False

        # Setup colors rgb
        if curses.can_change_color():
            for i in range(len(self.conf.color_set)):
                if not self.conf.color_set[i]:
                    continue
                else:
                    rgb = self.conf.color_set[i]
                    curses.init_color(i, rgb[0], rgb[1], rgb[2])

        curses.init_pair(0, curses.COLOR_BLACK, bgcolor)    # 0 black
        curses.init_pair(1, curses.COLOR_RED, bgcolor)      # 1 red
        curses.init_pair(2, curses.COLOR_GREEN, bgcolor)    # 2 green
        curses.init_pair(3, curses.COLOR_YELLOW, bgcolor)   # 3 yellow
        curses.init_pair(4, curses.COLOR_BLUE, bgcolor)     # 4 blue
        curses.init_pair(5, curses.COLOR_MAGENTA, bgcolor)  # 5 magenta
        curses.init_pair(6, curses.COLOR_CYAN, bgcolor)     # 6 cyan
        curses.init_pair(7, curses.COLOR_WHITE, bgcolor)    # 7 white

    def init_dict(self):
        self.timelines = ('home', 'mentions', 'direct', 'search', 'user', 'favorite')
        for b in self.timelines:
            self.statuses[b]   = []
            self.unread[b]     = 0
            self.count[b]      = 0
            self.last_read[b]  = 0

    def empty_dict(self, buffer):
        self.statuses[buffer]  = []
        self.unread[buffer]    = 0
        self.count[buffer]     = 0
        self.last_read[buffer] = 0

    def resize_event(self):
        self.resize_event = False
        curses.endwin()
        self.maxyx = self.screen.getmaxyx()
        curses.doupdate()


    def update_timeline(self, buffer):
        '''
        Retrieves tweets, don't display them
        @param the buffer to retreive tweets
        '''
        try:
            if not self.refresh_token:
                self.display_update_msg()
            # HOME
            if buffer == 'home':
                self.append_new_statuses(
                    self.api.update_home_timeline(), buffer)
            # MENTIONS
            elif buffer == 'mentions':
                self.append_new_statuses(
                    self.api.api.GetMentions(), buffer)
            # SEARCH
            elif buffer == 'search' and self.api.search_word != '':
                self.append_new_statuses(
                    self.api.api.GetSearch(self.api.search_word), buffer)
            # DIRECT
            elif buffer == 'direct':
                self.append_new_statuses(
                    self.api.api.GetDirectMessages(), buffer)
            # USER
            elif buffer == 'user' and self.api.search_user != '':
                self.append_new_statuses(
                    self.api.api.GetUserTimeline(self.api.search_user, include_rts=True), buffer)
            # FAVORITES
            elif buffer == 'favorite':
                self.append_new_statuses(self.api.api.GetFavorites(), buffer)

            # TODO does it realy need to display the timeline here ?!
            # DO NOT decomment it, unless the loop with the display_timeline and empty newstatuses
            # call here for checking (needed for start, and changing buffer, retrieves tweets in
            # this case
#            self.display_timeline()
        except:
            self.flash = ["Couldn't retrieve tweets", 'warning']
        self.count_statuses(buffer)
        self.count_unread(buffer)

    def append_new_statuses(self, newStatuses, buffer):
        '''This take care to add in the corresponding list new statuses
           that been retrieved, this just make sure lists are up ta date,
           and does not display them
           @param newStatuses are a list of new statuses retreives to append
           @param buffer used to know on wich list we appends tweets
        '''
        # Fresh new start.
        if self.statuses[buffer] == []:
            self.statuses[buffer] = newStatuses
        # This mean there is no new status, we just leave then.
        # TODO, this might meen we didn't fetch enought statuses
        elif newStatuses[0].id == self.statuses[buffer][0].id:
            pass
        # We may just don't have tweets, in case for DM for example
        elif len(newStatuses) == 0:
            pass
        # Finally, we append tweets
        else:
            for i in range(len(newStatuses)):
                if newStatuses[i].id == self.statuses[buffer][0].id:
                    self.statuses[buffer] = newStatuses[:i] + self.statuses[buffer]
                    # we don't want to move our current position
                    # if the update is in another buffer
                    if buffer == self.buffer:
                        self.status['current'] += len(newStatuses[:i])

    def count_statuses(self, buffer):
        self.count[buffer] = len(self.statuses[buffer])

    def count_unread(self, buffer):
        self.unread[buffer] = 0
        for i in range(len(self.statuses[buffer])):
            if self.statuses[buffer][i].id == self.last_read[buffer]:
                break
            self.unread[buffer] += 1
        self.unread[self.buffer] = 0

    def change_buffer(self, buffer):
        self.buffer = buffer
        self.status['current'] = 0
        self.status['first'] = 0
        self.count_unread(buffer)
        self.display_timeline()
    
    def navigate_buffer(self, nav):
        index = self.timelines.index(self.buffer)
        new_index = index + nav
        if new_index >= 0 and new_index < len(self.timelines):
            self.change_buffer(self.timelines[new_index])

    def display_flash(self):
        '''Should be the main entry to display Flash,
           it will take care of the warning/infor difference.
        '''
        msg = ' ' + self.flash[0] + ' '
        if self.flash[1] == 'warning':
            self.display_warning_msg(msg)
        else:
            self.display_info_msg(msg)
        self.flash = []

    def display_update_msg(self):
        self.display_info_msg(' Updating timeline... ')
        self.screen.refresh()

    def display_warning_msg(self, msg):
        self.screen.addstr(0, 3, msg, self.get_color('warning_msg'))

    def display_info_msg(self, msg):
        self.screen.addstr(0, 3, msg, self.get_color('info_msg'))

    def display_redraw_screen(self):
        self.screen.erase()
        self.display_timeline ()

    def display_timeline(self):
        '''Main entry to display a timeline, as it does not take arguments,
           make sure to set self.buffer before
        '''
        # It might have no tweets yet, we try to retrieve some then
        if len(self.statuses[self.buffer]) == 0:
            self.update_timeline(self.buffer)

        if not self.refresh_token:
            # The first status become the last_read for this buffer
            if len(self.statuses[self.buffer]) > 0:
                self.last_read[self.buffer] = self.statuses[self.buffer][0].id

            self.current_y = 1
            self.init_screen()
            for i in range(len(self.statuses[self.buffer])):
                if i >= self.status['first']:
                    br = self.display_status(self.statuses[self.buffer][i], i)
                    if not br:
                        break
            if len(self.flash) != 0:
                self.display_flash()
            if self.status['current'] > self.status['last']:
                self.status['current'] = self.status['last']
                self.display_timeline()

            # Activities bar
            if self.conf.params['activities']:
                self.display_activity()
            # Help bar
            if self.conf.params['help']:
                self.display_help_bar()

            self.screen.refresh()

    def display_activity(self):
        '''Main entry to display the activities bar'''
        maxyx = self.screen.getmaxyx()
        max_x = maxyx[1]
        self.screen.addstr(0, max_x - 23, ' ')
        for b in self.timelines:
            self.display_buffer_activities(b)
            self.display_counter_activities(b)

    def display_buffer_activities(self, buff):
        display = { 'home': 'H', 'mentions': 'M',
                    'direct': 'D', 'search': 'S ',
                    'user': 'U ', 'favorite': 'F', }
        if self.buffer == buff:
            self.screen.addstr(display[buff], self.get_color('current_tab'))
        else:
            self.screen.addstr(display[buff], self.get_color('other_tab'))

    def display_counter_activities(self, buff):
        if buff in ['home', 'mentions', 'direct']:
            if self.unread[buff] == 0:
                color = 'read'
            else:
                color = 'unread'

            self.screen.addstr(':%s ' % str(self.unread[buff]), self.get_color(color))

    def display_help_bar(self):
        '''The help bar display at the bottom of the screen,
           for keysbinding reminder'''
        maxyx = self.screen.getmaxyx()
        self.screen.addnstr(maxyx[0] -1, 2,
            'help:? up:%s down:%s tweet:%s retweet:%s reply:%s home:%s mentions:%s update:%s' %
                           (chr(self.conf.keys['up']),
                            chr(self.conf.keys['down']),
                            chr(self.conf.keys['tweet']),
                            chr(self.conf.keys['retweet']),
                            chr(self.conf.keys['reply']),
                            chr(self.conf.keys['home']),
                            chr(self.conf.keys['mentions']),
                            chr(self.conf.keys['update']),
                           ), max[1] -4, self.get_color('text')
        )

    def display_status (self, status, i):
        ''' Display a status (tweet) from top to bottom of the screen,
        depending on self.current_y, an array [status, panel] is return and
        will be stock in a array, to retreve status information (like id)
        @param status, the status to display
        @param i, to know on witch status we're display (this could be refactored)
        @return True if the tweet as been displayed, to know it may carry on to display some
                more, otherwise return False
        '''

        # Check if we have a retweet
        self.is_retweet(status)

        # The content of the tweets is handle
        # text is needed for the height of a panel
        self.charset = sys.stdout.encoding
        header  = self.get_header(status)

        # We get size and where to display the tweet
        size = self.get_size_status(status)
        length = size['length']
        height = size['height']
        start_y = self.current_y
        start_x = 2

        # We leave if no more space left
        if start_y + height +1 > self.maxyx[0]:
            return False

        panel = curses.newpad(height, length)

        if self.conf.params['tweet_border'] == 1:
            panel.border(0)

        # Highlight the current status
        if self.status['current'] == i:
            panel.addstr(0,3, header, self.get_color('current_tweet'))
        else:
            panel.addstr(0, 3, header, self.get_color('header'))

        self.display_text(panel, status)

        panel.refresh(0, 0, start_y, start_x,
            start_y + height, start_x + length)
        # An adjustment to compress a little the display
        if self.conf.params['compress']:
            c = -1
        else:
            c = 0

        self.current_y = start_y + height + c
        self.status['last'] = i

        return True

    def get_text(self, status):
        text = status.text.encode(self.charset)
        text = text.replace('\n', ' ')
        if status.rt:
            text = text.split(':')[1:]
            text = ':'.join(text)

            if hasattr(status, 'retweeted_status'):
                if hasattr(status.retweeted_status, 'text') \
                        and len(status.retweeted_status.text) > 0:
                    text = status.retweeted_status.text
        return text

    def display_text(self, panel, status):
        '''needed to cut words properly, as it would cut it in a midle of a
        world without. handle highlighting of '#' and '@' tags.
        '''
        text = self.get_text(status)
        words = text.split(' ')
        curent_x = 2
        line = 1
        for word in words:
            if curent_x + len(word) > self.maxyx[1] -6:
                line += 1
                curent_x = 2

            if word != '':
                # The word is an HASHTAG ? '#'
                if word[0] == '#':
                    panel.addstr(line, curent_x, word, self.get_color('hashtag'))
                # Or is it an 'AT TAG' ? '@'
                elif word[0] == '@':
                    name = self.api.myself.screen_name
                    # The AT TAG is,  @myself
                    if word == '@'+name or word == '@'+name+':':
                        panel.addstr(line, curent_x, word, self.get_color('highlight'))
                    # @anyone
                    else:
                        panel.addstr(line, curent_x, word, self.get_color('attag'))
                # It's just a normal word
                else:
                    try:
                        panel.addstr(line, curent_x, word, self.get_color('text'))
                    except:
                        pass
                curent_x += len(word) + 1

                # We check for ugly empty spaces
                while panel.inch(line, curent_x -1) == ord(' ') and panel.inch(line, curent_x -2) == ord(' '):
                    curent_x -= 1

    def get_size_status(self, status):
        '''Allow to know how height will be the tweet, it calculate it exactly
           as it will display it.
        '''
        length = self.maxyx[1] - 4
        x = 2
        y = 1
        txt = self.get_text(status)
        words = txt.split(' ')
        for w in words:
            if x+len(w) > length - 2:
                y += 1
                x =  2
            x += len(w)+1

        height = y + 2
        size = {'length': length, 'height': height}
        return size

    def get_time(self, status):
        '''Handle the time format given by the api with something more
        readeable
        @param  date: full iso time format
        @return string: readeable time
        '''
        if self.conf.params['relative_time'] == 1 and self.buffer != 'direct':
            hour =  status.GetRelativeCreatedAt()
        else:
            hour = time.gmtime(status.GetCreatedAtInSeconds() - time.altzone)
            hour = time.strftime('%H:%M', hour)

        return hour

    def get_header(self, status):
        '''@return string'''
        charset = sys.stdout.encoding
        try:
            pseudo  = status.user.screen_name.encode(charset)
        except:
            # Only for the Direct Message case
            pseudo = status.sender_screen_name.encode(charset)
        time    = self.get_time(status)
        #name    = status.user.name.encode(charset)

        if status.rt and self.conf.params['retweet_by'] == 1:
            rtby = pseudo
            origin = self.origin_of_retweet(status)
            header = ' %s (%s) RT by %s ' % (origin, time, rtby)
        else:
            header = " %s (%s) " % (pseudo, time)

        return header

    def is_retweet(self, status):
        status.rt = self.regex_retweet.match(status.text)
        return status.rt

    def origin_of_retweet(self, status):
        '''When its a retweet, return the first person who tweet it,
           not the retweeter
        '''
        origin = status.text
        origin = origin[4:]
        origin = origin.split(':')[0]
        origin = str(origin)
        return origin

    def tear_down(self, *dummy):
        '''Last function call when quiting, restore some defaults params'''
        self.screen.keypad(0)
        curses.echo()
        curses.nocbreak()
        curses.curs_set(1)
        curses.endwin()

    def sigwinch_handler(self, *dummy):
        '''Resize event callback'''
        self.resize_event = True

    def clear_statuses(self):
        self.statuses[self.buffer] = [self.statuses[self.buffer][0]]
        self.count_statuses(self.buffer)
        self.status['current'] = 0

    def get_current_status(self):
        '''@return the status object itself'''
        return self.statuses[self.buffer][self.status['current']]

    def get_urls(self):
        '''
        @return array of urls find in the text
        '''
        return re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', self.statuses[self.buffer][self.status['current']].text)

    def get_color(self, color):
        '''Return the curses code, with bold if enable of the color
           given in argument of the function
           @return color_pair code
        '''
        cp = curses.color_pair(self.conf.colors[color]['c'])
        if self.conf.colors[color]['b']:
            cp |= curses.A_BOLD

        return cp

    def move_down(self):
        if self.status['current'] < self.count[self.buffer] - 1:
            if self.status['current'] >= self.status['last']:
                self.status['first'] += 1
            self.status['current'] += 1

    def move_up(self):
        if self.status['current'] > 0:
            # if we need to move up the list to display
            if self.status['current'] == self.status['first']:
                self.status['first'] -= 1
            self.status['current'] -= 1

    def back_on_bottom(self):
        self.ui.status['current'] = self.ui.status['last']

    def openurl(self):
        urls = self.getUrls()
        for url in urls:
            #try:
            os.system(self.conf.params['openurl_command'] % url)
            #except:
                #self.ui.Flash  = ["Couldn't open url", 'warning']