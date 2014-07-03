from __future__ import print_function
import json
import time
import os
import logging
import datetime
from collections import OrderedDict

from flask import Flask, render_template
import requests
from apscheduler.scheduler import Scheduler
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Float, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import newrelic.agent

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


##############
# REQUIREMENTS
# 1) Python 2.7+, plus all the modules listed in requirements.txt
# 2) Expects the VCAP (CloudFoundry) variables to be set....so if you run this locally as a dev instance, you'll need to set them...see below for a working example.

services = json.loads(os.environ['VCAP_SERVICES'])
elephantsql = services['elephantsql']
elephant_url = elephantsql[0]['credentials']['uri']

cp_user = os.environ['cp_user']
cp_pass = os.environ['cp_pass']

sched = Scheduler()
sched.start()


engine = create_engine('postgres://cvepxgvj:4oXkHJk_BMR601gUBg4CAmM5P3lEkkcn@babar.elephantsql.com:5432/cvepxgvj', echo=True)
Session.configure(bind=engine)  # once engine is available
session = Session()

Base.metadata.create_all(engine)

cached_counts = OrderedDict()
cached_counts_time = 0
min_cache_interval = 30

app = Flask(__name__)
cpsession = requests.session()
cpsession.headers.update(
        {
        'Accept':'*/*',
        'X-Requested-With':'XMLHttpRequest',
        'Referer':'https://na.chargepoint.com/',
        'User-Agent':"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.76.4 (KHTML, like Gecko) Version/7.0.4 Safari/537.76.4",
        'Host': 'na.chargepoint.com'
        }
)
urls = {
    'vmware':"https://na.chargepoint.com/dashboard/getChargeSpots?&lat=37.39931348058685&lng=-122.1379984047241&ne_lat=37.40442723948339&ne_lng=-122.11644417308042&sw_lat=37.39419937272119&sw_lng=-122.15955263636778&user_lat=37.8317378&user_lng=-122.20247309999999&search_lat=37.4418834&search_lng=-122.14301949999998&sort_by=distance&f_estimationfee=false&f_available=true&f_inuse=true&f_unknown=true&f_cp=true&f_other=false&f_l3=true&f_l2=true&f_l1=false&f_estimate=false&f_fee=true&f_free=true&f_reservable=false&f_shared=true&driver_connected_station_only=false&community_enabled_only=false&_=1403829649942",
    'emc':"https://na.chargepoint.com/dashboard/getChargeSpots?&lat=37.38877696416435&lng=-121.97968816798402&ne_lat=37.39005561633451&ne_lng=-121.9742996100731&sw_lat=37.38749829018581&sw_lng=-121.98507672589494&user_lat=37.8317378&user_lng=-122.20247309999999&search_lat=37.388615&search_lng=-121.98040700000001&sort_by=distance&f_estimationfee=false&f_available=true&f_inuse=true&f_unknown=true&f_cp=true&f_other=false&f_l3=true&f_l2=true&f_l1=false&f_estimate=false&f_fee=true&f_free=true&f_reservable=false&f_shared=true&driver_connected_station_only=false&community_enabled_only=false&_=1403829763999"

}
garage_mapping = {
    "PG3":"Creekside",
    "PG1":"Hilltop",
    "PG2":"Central",
    "SANTA":"EMC"
}



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
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

def current_time():
    """


    :return: :rtype: int
    """
    return int(time.time())

def push_to_db():
    """
    Pushes the current info into the DB.

    """
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
    session.commit()

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

    most_recent_timestamp = 0
    for record in session.query(StationTimeSeriesRecord).order_by(desc(StationTimeSeriesRecord.timestamp)).limit(1):
        most_recent_timestamp = record.timestamp
    counts = OrderedDict()
    for record in session.query(GarageCurrentSummary).filter_by(timestamp=most_recent_timestamp).order_by(GarageCurrentSummary.garage):
        if record.garage not in counts:
            counts[record.garage] = {'total': 0, 'available':0, 'percent': 0}
        counts[record.garage]['total'] += record.total
        counts[record.garage]['available'] += record.available
        counts[record.garage]['percent'] += record.percent


    cached_counts=counts
    cached_counts_time=current_time()
    return counts

def get_history_for_station(station_name, limit=100):
    """

    :param station_name: string
    :param limit: int
    :return: :rtype: list
    """
    to_return = []
    for record in session.query(StationTimeSeriesRecord).filter_by(station_name=station_name).order_by(desc(StationTimeSeriesRecord.timestamp)).limit(limit):
        to_return.append(record)
    return to_return

def get_history_for_garage(garage,limit=100):
    """

    :param garage: string
    :param limit: int
    """
    for record in session.query(GarageCurrentSummary).filter_by(garage=garage).order_by(desc(GarageCurrentSummary.timestamp)):
        print(record)


@app.route('/', defaults={'forceupdate': ""})
@app.route('/<forceupdate>')
def dashboard(forceupdate):
    if forceupdate == 'forceupdate':
        push_to_db()
    message = session.query(SpecialMessage).order_by(desc(SpecialMessage.timestamp)).limit(1)[0].message
    return render_template('default.html',counts=gen_live_counts(),currenttime=humantime(current_time()),updated=humantime(cached_counts_time),message=message)

@app.route('/garagehistory/<garage_name>')
def display_garage_history(garage_name):
    get_history_for_garage(garage_name,limit=100)
    return ""

@app.route('/stationhistory/<station_name>')
def display_station_history(station_name):
    get_history_for_station(station_name,limit=100)
    return ""

if __name__ == '__main__':
    sched.add_interval_job(push_to_db,minutes=2)
    port = os.getenv('VCAP_APP_PORT', '5000')
    logging.info("Running on port " + port)
    logging.info(str(os.environ))
    app.run(debug=True,port=int(port),host='0.0.0.0')
