from __future__ import print_function
import json
import time
import os
import logging
import datetime
from collections import OrderedDict
from pprint import pformat
import copy

from dateutil import tz
from flask import Flask, render_template, request
import requests
from apscheduler.scheduler import Scheduler
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import InvalidRequestError
import newrelic.agent
from config import Config


cfg = Config(open(os.environ['CONFIG_FILE']))

newrelic.agent.initialize('newrelic.ini')

logging.basicConfig(level=logging.DEBUG)

Base = declarative_base()
Session = sessionmaker()

class StationTimeSeriesRecord(Base):
    __tablename__ = 'station_timeseries'
    id = Column(Integer, primary_key=True)
    timestamp = Column(Integer, index=True)
    station_name = Column(String)
    available = Column(Integer)
    total = Column(Integer)
    garage = Column(String)
    def __repr__(self):
       return "<StationTimeSeries Record (station_name='%s', timestamp=%s, stats=%s/%s)>" % (self.station_name, self.timestamp, self.available,self.total)

class GarageCurrentSummary(Base):
    __tablename__ = 'TOTALS_PER_GARAGE'
    primkey = Column(String, primary_key=True)
    timestamp = Column(Integer)
    garage = Column(String)
    available = Column(Integer)
    total=Column(Integer)
    percent=Column(Float)
    def __repr__(self):
       return "<GarageCurrentSummary Record (garage='%s', timestamp=%s, stats=%s/%s)>" % (self.garage, self.timestamp, self.available,self.total)

class SpecialMessage(Base):
    __tablename__ = 'special_messages'
    id = Column(Integer, primary_key=True)
    timestamp = Column(Integer, index=True)
    message = Column(String)
    def __repr__(self):
       return "<SpecialMessage Record (timestamp=%s message=%s)>" % (self.timestamp, self.message)

elephant_url = cfg.sql_url
cp_user = cfg.cp_user
cp_pass = cfg.cp_pass

if 'VCAP_SERVICES' in os.environ:
    services = json.loads(os.environ['VCAP_SERVICES'])
    elephantsql = services['elephantsql']
    elephant_url = elephantsql[0]['credentials']['uri']
    logging.basicConfig(level=logging.CRITICAL)


sched = Scheduler()
sched.start()

engine = create_engine(elephant_url)

Session.configure(bind=engine)  # once engine is available

Base.metadata.create_all(engine)

cached_counts = OrderedDict()
cached_counts_time = 0
min_cache_interval = 300

app = Flask(__name__)
cpsession = requests.session()
cpsession.headers.update(cfg.chargepoint_session_headers)
urls = cfg.urls
garage_mapping = cfg.garage_mapping



def do_login(cpuser,cppassword):
    """

    :param cpuser: string
    :param cppassword: string
    :return: :rtype: string
    """
    form_data = {
        'user_name': cpuser,
        'user_password': cppassword,
        'recaptcha_response_field': '',
        'timezone_offset': '480',
        'timezone': 'PST',
        'timezone_name': ''
    }
    auth = cpsession.post(url='https://na.chargepoint.com/users/validate',data=form_data)
    return auth.json()

def get_stations_info(location):
    """

    :param location: string
    :return: :rtype: list
    """
    url = urls[location]
    logging.debug("Getting Data for " + location + " from " + url)
    station_data = cpsession.get(url)
    return json.loads(station_data.text)[0]['station_list']['summaries']

def munge_raw(station_info,filter=None):
    """

    :param station_info:list
    :param filter: string
    :return: :rtype: list
    """
    all_stations = []
    for station in station_info:
        new_station = {}
        new_station['name'] = ".".join(station['station_name']).replace(" ",".").replace("-STATION","")
        logging.debug("Processing Station " + new_station['name'])
        if filter.upper() not in new_station['name']:
            logging.debug("Station " + new_station['name'] + " was the wrong prefix")
            continue
        new_station['port_count'] = station['port_count']['total']
        if 'available' in station['port_count']:
            new_station['ports_available'] = station['port_count']['available']
        else:
            new_station['ports_available'] = 0
        all_stations.append(new_station)
        logging.debug("Added new station to the list: " + str(new_station))

    return all_stations

def humantime(timestamp):
    """

    :param timestamp: int
    :return: :rtype: string
    """
    assert timestamp > 0
    from_zone = tz.gettz('UTC')
    to_zone = tz.gettz('America/Los_Angeles')
    utc = datetime.datetime.fromtimestamp(timestamp).replace()
    utc = utc.replace(tzinfo=from_zone)
    pacific = utc.astimezone(to_zone)
    return pacific.strftime("%a, %d %b %Y %H:%M:%S")

def current_time():
    """


    :return: :rtype: int
    """
    return int(time.time())

def push_to_db():
    """
    Pushes the current info into the DB.

    """
    session = Session()
    do_login(cp_user,cp_pass)
    timestamp = int(time.time())
    all_locations = []
    for location in urls.keys():
        raw = get_stations_info(location)
        munged = munge_raw(raw,location)
        all_locations += munged

    for status in all_locations:
        record = StationTimeSeriesRecord()
        record.timestamp = timestamp
        record.station_name = status['name']
        record.total = int(status['port_count'])
        record.available = int(status['ports_available'])
        garage_hint = record.station_name.split('.')[1]
        record.garage = garage_mapping[garage_hint]
        session.add(record)
    try:
        session.commit()
    except InvalidRequestError, e:
        session.rollback()
        raise e
    finally:
        session.close()

def gen_live_counts():
    """
    Returns a cached or live copy of the per-garage counts.

    :return: :rtype: OrderedDict
    """

    global cached_counts
    global cached_counts_time
    #Lets check for a cached version first
    if current_time() - min_cache_interval < cached_counts_time:
        #we are within our cache window, so lets return the previous one
        logging.info("Returning Cached counts...")
        return cached_counts

    #otherwise, actually go get the data
    session = Session()
    most_recent_timestamp = 0
    for record in session.query(StationTimeSeriesRecord).order_by(desc(StationTimeSeriesRecord.timestamp)).limit(1):
        most_recent_timestamp = record.timestamp
    counts = OrderedDict()
    for record in session.query(GarageCurrentSummary).filter_by(timestamp=most_recent_timestamp).order_by(GarageCurrentSummary.garage):
        if record.garage not in counts:
            counts[record.garage] = {'total': 0, 'available':0, 'percent': 0}
        counts[record.garage]['total'] += record.total
        counts[record.garage]['available'] += record.available
        counts[record.garage]['percent'] += int(record.percent)

    session.close()
    cached_counts=copy.deepcopy(counts)
    cached_counts_time=most_recent_timestamp
    return counts

def get_history_for_station(station_name, limit=100):
    """

    :param station_name: string
    :param limit: int
    :return: :rtype: list
    """
    session = Session()
    to_return = []
    for record in session.query(StationTimeSeriesRecord).filter_by(station_name=station_name).order_by(desc(StationTimeSeriesRecord.timestamp)).limit(limit):
        to_return.append(record)
    session.close()
    return to_return

def get_history_for_garage(garage,limit=100):
    """

    :param garage: string
    :param limit: int
    """
    session = Session()
    for record in session.query(GarageCurrentSummary).filter_by(garage=garage).order_by(desc(GarageCurrentSummary.timestamp)):
        print(record)
    session.close()

@app.route('/message',methods=['POST', 'GET'])
def add_message():
    if request.method == 'POST':
        if 'message' in request.form:
            session = Session()
            record = SpecialMessage()
            record.timestamp = current_time()
            record.message = request.form['message']
            session.add(record)
            try:
                session.commit()
            except InvalidRequestError, e:
                session.rollback()
                raise e
            finally:
                session.close()

    return render_template('addupdate.html')

@app.route('/', defaults={'forceupdate': ""})
@app.route('/<forceupdate>')
def dashboard(forceupdate):
    session = Session()
    if forceupdate == 'forceupdate':
        push_to_db()
    message = session.query(SpecialMessage).order_by(desc(SpecialMessage.timestamp)).limit(1)[0].message
    session.close()
    return render_template('default.html',counts=gen_live_counts(),currenttime=humantime(current_time()),updated=humantime(cached_counts_time),message=message)

@app.route('/garagehistory/<garage_name>')
def display_garage_history(garage_name):
    get_history_for_garage(garage_name,limit=100)
    return ""

@app.route('/stationhistory/<station_name>')
def display_station_history(station_name):
    get_history_for_station(station_name,limit=100)
    return ""

@app.route('/config')
def config():
    return render_template('minimal.html',message=pformat(os.environ,indent=4))

if __name__ == '__main__':
    sched.add_interval_job(push_to_db,minutes=2)
    port = os.getenv('VCAP_APP_PORT', '5000')
    logging.info("Running on port " + port)
    logging.info(str(os.environ))
    app.run(debug=True,port=int(port),host='0.0.0.0')
