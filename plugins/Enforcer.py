#!/usr/bin/env python

###
# Copyright (c) 2002, Jeremiah Fincher
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

"""
ChannelEnforcer: Enforces capabilities on a channel, watching MODEs, KICKs,
                 JOINs, etc. to make sure they match the channel's config.
"""

from baseplugin import *

import conf
import ircdb
import ircmsgs
import privmsgs
import ircutils


###
# ChannelEnforcer: Enforces capabilities on JOIN, MODE, KICK, etc.
###
_chanCap = ircdb.makeChannelCapability
class ChannelEnforcer(callbacks.Privmsg):
    def startenforcer(self, irc, msg, args):
        """[<CHANSERV> <revenge> <topicPrefix>]"""
        self.topics = {}
        (chanserv, revenge) = privmsgs.getArgs(args, needed=0, optional=2)
        self.chanserv = chanserv or 'ChanServ'
        self.started = True
        self.reply(irc, msg, conf.replySuccess)
    startenforcer = privmsgs.checkCapability(startenforcer, 'admin')

    def doJoin(self, irc, msg):
        channel = msg.args[0]
        c = ircdb.channels.getChannel(channel)
        if c.checkBan(msg.prefix):
            irc.queueMsg(ircmsgs.ban(channel, ircutils.banmask(msg.prefix)))
            irc.queueMsg(ircmsgs.kick(channel, msg.nick))
        elif ircdb.checkCapability(msg.prefix, _chanCap(channel, 'op')):
            irc.queueMsg(ircmsgs.op(channel, msg.nick))
        elif ircdb.checkCapability(msg.prefix, _chanCap(channel, 'halfop')):
            irc.queueMsg(ircmsgs.halfop(channel, msg.nick))
        elif ircdb.checkCapability(msg.prefix, _chanCap(channel, 'voice')):
            irc.queueMsg(ircmsgs.voice(channel, msg.nick))

    def doTopic(self, irc, msg):
        channel = msg.args[0]
        topic = msg.args[1]
        if msg.nick != irc.nick and \
           not ircdb.checkCapabilities(msg.prefix,
                                       (_chanCap(channel, 'op'),
                                        _chanCap(channel, 'topic'))):
            irc.queueMsg(ircmsgs.topic(channel, self.topics[channel]))
            if self.revenge:
                irc.queueMsg(ircmsgs.kick(channel, msg.nick,
                                      conf.replyNoCapability % \
                                      _chanCap(channel, 'topic')))
        elif not topic.startswith(self.topicPrefix):
            irc.queueMsg(ircmsgs.topic(channel, self.topicPrefix + topic))
            if self.revenge:
                irc.queueMsg(ircmsgs.kick(channel, msg.nick,
                  'Topics must begin with the prefix "%s"' % self.topicPrefix))
        else:
            self.topics[channel] = msg.args[1]

    def do332(self, irc, msg):
        # This command gets sent right after joining a channel.
        (channel, topic) = msg.args[1:]
        self.topics[channel] = topic

    def _isProtected(self, channel, hostmask):
        capabilities = [_chanCap(channel, 'op'),_chanCap(channel, 'protected')]
        return ircdb.checkCapabilities(hostmask, capabilities)

    def _revenge(self, irc, channel, hostmask):
        irc.queueMsg(ircmsgs.ban(channel, ircutils.banmask(hostmask)))
        irc.queueMsg(ircmsgs.kick(channel,ircutils.nickFromHostmask(hostmask)))

    def doKick(self, irc, msg):
        channel = msg.args[0]
        kicked = msg.args[1].split(',')
        deop = False
        if msg.nick != irc.nick and\
           not ircdb.checkCapability(msg.prefix, _chanCap(channel, 'op')):
            for nick in kicked:
                hostmask = irc.state.nickToHostmask(nick)
                if self._isProtected(channel, hostmask):
                    deop = True
                    irc.queueMsg(ircmsgs.invite(channel, msg.args[1]))
            if deop:
                deop = False
                if self.revenge:
                    self._revenge(irc, channel, msg.prefix)
                else:
                    irc.queueMsg(ircmsgs.deop(channel, msg.nick))

    def doMode(self, irc, msg):
        channel = msg.args[0]
        if not ircutils.isChannel(channel):
            return
        if msg.nick != irc.nick and\
           not ircdb.checkCapability(msg.prefix, _chanCap(channel, 'op')):
            for (mode, value) in ircutils.separateModes(msg.args[1:]):
                if value == msg.nick:
                    continue
                elif mode == '+o' and value != irc.nick:
                    hostmask = irc.state.nickToHostmask(value)
                    if ircdb.checkCapability(channel,
                                           ircdb.makeAntiCapability('op')):
                        irc.queueMsg(ircmsgs.deop(channel, value))
                elif mode == '+h' and value != irc.nick:
                    hostmask = irc.state.nickToHostmask(value)
                    if ircdb.checkCapability(channel,
                                           ircdb.makeAntiCapability('halfop')):
                        irc.queueMsg(ircmsgs.dehalfop(channel, value))
                elif mode == '+v' and value != irc.nick:
                    hostmask = irc.state.nickToHostmask(value)
                    if ircdb.checkCapability(channel,
                                           ircdb.makeAntiCapability('voice')):
                        irc.queueMsg(ircmsgs.devoice(channel, value))
                elif mode == '-o':
                    hostmask = irc.state.nickToHostmask(value)
                    if self._isProtected(channel, hostmask):
                        irc.queueMsg(ircmsgs.op(channel, value))
                        if self.revenge:
                            self._revenge(irc, channel, msg.prefix)
                        else:
                            irc.queueMsg(ircmsgs.deop(channel, msg.nick))
                elif mode == '-h':
                    hostmask = irc.state.nickToHostmask(value)
                    if self._isProtected(channel, hostmask):
                        irc.queueMsg(ircmsgs.halfop(channel, value))
                        if self.revenge:
                            self._revenge(irc, channel, msg.prefix)
                        else:
                            irc.queueMsg(ircmsgs.deop(channel, msg.nick))
                elif mode == '-v':
                    hostmask = irc.state.nickToHostmask(value)
                    if self._isProtected(channel, hostmask):
                        irc.queueMsg(ircmsgs.voice(channel, value))
                        if self.revenge:
                            self._revenge(irc, channel, msg.prefix)
                        else:
                            irc.queueMsg(ircmsgs.deop(channel, msg.nick))
                elif mode == '+b':
                    # To be safe, only #channel.ops are allowed to ban.
                    if not ircdb.checkCapability(msg.prefix,
                                                 _chanCap(channel, 'op')):
                        irc.queueMsg(ircmsgs.unban(channel, value))
                        if self.revenge:
                            self._revenge(irc, channel, msg.prefix)
                        else:
                            irc.queueMsg(ircmsgs.deop(channel, msg.nick))

    def __call__(self, irc, msg):
        if msg.prefix == self.chanserv:
            return
        else:
            return BasePlugin.__call__(self, irc, msg)


Class = ChannelEnforcer
# vim:set shiftwidth=4 tabstop=8 expandtab textwidth=78:
