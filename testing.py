__author__ = 'mcowger'

# import requests
#
#
# session = requests.session()
# session.headers.update(
#         {
#         'Accept':'*/*',
#         'X-Requested-With':'XMLHttpRequest',
#         'Referer':'https://na.chargepoint.com/',
#         'User-Agent':"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.76.4 (KHTML, like Gecko) Version/7.0.4 Safari/537.76.4",
#         'Host': 'na.chargepoint.com'
#         }
# )
#
# cpuser='matt@cowger.us'
# cppassword = 'Habloo12'
# form_data = {
#     'user_name': cpuser,
#     'user_password': cppassword,
#     'recaptcha_response_field': '',
#     'timezone_offset': '420',
#     'timezone': 'PST',
#     'timezone_name': ''
# }
# auth = session.post(url='https://na.chargepoint.com/users/validate',data=form_data)
# print(auth.text)
#
#
# vmw_url = "https://na.chargepoint.com/dashboard/getChargeSpots?&lat=37.39931348058685&lng=-122.1379984047241&ne_lat=37.40442723948339&ne_lng=-122.11644417308042&sw_lat=37.39419937272119&sw_lng=-122.15955263636778&user_lat=37.8317378&user_lng=-122.20247309999999&search_lat=37.4418834&search_lng=-122.14301949999998&sort_by=distance&f_estimationfee=false&f_available=true&f_inuse=true&f_unknown=true&f_cp=true&f_other=true&f_l3=true&f_l2=true&f_l1=false&f_estimate=false&f_fee=true&f_free=true&f_reservable=false&f_shared=true&driver_connected_station_only=false&community_enabled_only=false&_=1403829649942"
# emc_url = "https://na.chargepoint.com/dashboard/getChargeSpots?&lat=37.38877696416435&lng=-121.97968816798402&ne_lat=37.39005561633451&ne_lng=-121.9742996100731&sw_lat=37.38749829018581&sw_lng=-121.98507672589494&user_lat=37.8317378&user_lng=-122.20247309999999&search_lat=37.388615&search_lng=-121.98040700000001&sort_by=distance&f_estimationfee=false&f_available=true&f_inuse=true&f_unknown=true&f_cp=true&f_other=true&f_l3=true&f_l2=true&f_l1=false&f_estimate=false&f_fee=true&f_free=true&f_reservable=false&f_shared=true&driver_connected_station_only=false&community_enabled_only=false&_=1403829763999"
# stations = session.get(emc_url)
# print(stations.text)
