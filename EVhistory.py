from __future__ import print_function
from flask import Flask, render_template
from redis import StrictRedis
import requests
import json
import time
import os
import logging
import pprint
from collections import OrderedDict
import datetime
from apscheduler.scheduler import Scheduler

logging.basicConfig(level=logging.DEBUG)


##############
# REQUIREMENTS
# 1) Python 2.7+, plus all the modules listed in requirements.txt
# 2) Expects the VCAP (CloudFoundry) variables to be set....so if you run this locally as a dev instance, you'll need to set them...see below for a working example.
# 3) A redis instance (I used redis-cloud).
# Example for environment variables:
# VCAP_SERVICES="{     "rediscloud": [         {             "name": "redis",             "label": "rediscloud",             "tags": [                 "key-value",                 "redis",                 "Data Store"             ],             "plan": "25mb",             "credentials": {                 "port": "16505",                 "hostname": "redis-hostname",                 "password": "redispassword"             }         }     ] }"
# cp_user="user@chargepoint.com"
# cp_pass="password"



vcap_services = os.environ['VCAP_SERVICES']
parsed_service = json.loads(vcap_services)
rediscloud = parsed_service['rediscloud']
credentials = rediscloud[0]['credentials']

#
#
redis_db = None
redis_password = credentials['password']
redis_host = credentials['hostname']
redis_port = credentials['port']
#

cp_user = os.environ['cp_user']
cp_pass = os.environ['cp_pass']

debug=False

sched = Scheduler()
sched.start()



app = Flask(__name__)
session = requests.session()
session.headers.update(
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

r = StrictRedis(host=redis_host,port=redis_port,db=redis_db,password=redis_password)


def do_login(cpuser,cppassword):
    form_data = {
        'user_name': cpuser,
        'user_password': cppassword,
        'recaptcha_response_field': '',
        'timezone_offset': '480',
        'timezone': 'PST',
        'timezone_name': ''
    }
    auth = session.post(url='https://na.chargepoint.com/users/validate',data=form_data)
    return auth.json()


def get_stations_info(location):
    url = urls[location]
    logging.debug("Getting Data for " + location + " from " + url)
    station_data = session.get(url)
    return json.loads(station_data.text)[0]['station_list']['summaries']

def get_state(station_info,filter=None):
    all_stations = []
    for station in station_info:

        #print(station)
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

def push_data_to_db(station_data):
    pipeline = r.pipeline()
    for station in station_data:
        date = int(time.time())
        to_push = json.dumps({'timestamp': date, 'station_info':station})
        logging.debug("Pushing to Redis:" + to_push)
        pipeline.lpush(station['name'],to_push)
        pipeline.ltrim(station['name'],0,1000) #ensure we dont keep more than 100 datapoints.
    pipeline.execute()

def rollup_current_data():
    counts = OrderedDict()
    counts["Central"] = {"total": 0, 'available':0}
    counts["Creekside"] = {"total": 0, 'available':0}
    counts["Hilltop"] = {"total": 0, 'available':0}
    counts["EMC"]  = {"total": 0, 'available':0}

    key_list = r.keys("*.*")
    raw_bytes = []
    pipeline = r.pipeline()
    for key in key_list:
        info = pipeline.lrange(key,0,0)
    for response in pipeline.execute():
        record = json.loads(response[0].decode())
        garage_short = record['station_info']['name'].split(".")[1]
        garage_long = garage_mapping[garage_short]
        ports_available_add = record['station_info']['ports_available']
        ports_count_add = record['station_info']['port_count']
        counts[garage_long]['total'] += ports_count_add
        counts[garage_long]['available'] += ports_available_add
    return counts

def update_sites():
    timestamp = int(time.time())
    auth = do_login(cp_user,cp_pass)
    if auth['auth'] != True:
        raise "Failed to Authenticate!"
    for site,url in urls.items():
        logging.debug("Beginning for site: " + site)
        station_info = get_stations_info(location=site)
        station_data = get_state(station_info,filter=site)
        push_data_to_db(station_data)
    r.set('lastcheck',timestamp)



@app.route('/')
def dashboard():


    counts=rollup_current_data()
    humantime = datetime.datetime.fromtimestamp(int(r.get("lastcheck"))).strftime("%Y-%m-%d %H:%M:%S")
    return render_template("default.html",counts=counts,updated=humantime)


if __name__ == '__main__':
    sched.add_interval_job(update_sites,minutes=1)
    port = os.getenv('VCAP_APP_PORT', '5000')
    logging.info("Running on port " + port)
    logging.info(str(os.environ))
    app.run(debug=False,port=int(port),host='0.0.0.0')

#_--------------------------------------
