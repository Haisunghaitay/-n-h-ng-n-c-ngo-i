import asyncio
import json
import os
import logging
from dotenv import load_dotenv
load_dotenv()
import html
import re
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, CopyTextButton
from aiogram.webhook.aiohttp_handler import SimpleRequestHandler, setup_application
from aiohttp import web
import anousith_api
import vet_api
import hal_api
import tdffm_api

# Cfrom aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
