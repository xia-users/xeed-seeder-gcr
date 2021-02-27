import os
import base64
import gzip
import json
from functools import wraps
from flask import Flask, request, Response, render_template, current_app
from google.cloud import pubsub_v1
from xialib_pubsub import PubsubPublisher
from pyxeed import Seeder

app = Flask(__name__)
pub_client = pubsub_v1.PublisherClient()

# Simple Authentification Service
def check(authorization_header):
    username = os.environ.get('XEED_USER', "user")  # Internal Usage oriented
    password = os.environ.get('XEED_PASSWORD', "La_vie_est_belle") # Internal Usage oriented
    encoded_uname_pass = authorization_header.split()[-1]
    if encoded_uname_pass == base64.b64encode((username + ":" + password).encode()).decode():
        return True

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        authorization_header = request.headers.get('Authorization')
        if authorization_header and check(authorization_header):
            return f(*args, **kwargs)
        else:
            resp = Response()
            resp.headers['WWW-Authenticate'] = 'Basic'
            return resp, 401
    return decorated

@app.route('/')
def main():
    return render_template("index.html")

@app.route('/push',methods=['GET', 'POST'])
@login_required
def push():
    global pub_client
    http_header_dict = dict(request.headers)
    msg_headers = {key.lower()[5:].replace('-', '_'): value for (key, value) in http_header_dict.items() if
                  key.lower().startswith('xeed-')}
    destination = current_app.config["DESTINATION"]
    topic_id = current_app.config["TOPIC_ID"]
    table_id = msg_headers.get('table_id', "")

    active_publisher = PubsubPublisher(pub=pub_client)
    publisher = {'pubsub': active_publisher}
    seeder = Seeder(publisher=publisher)

    if request.method == 'GET':
        if active_publisher.check_destination(destination, topic_id):
            return render_template("message.html", project=destination, topic=topic_id)
        else:
            return 'Destination/Topic not found', 400

    if http_header_dict.get('Content-Encoding', 'gzip') != 'gzip':
        return 'Content must be flat or gzip-encoded', 400

    if topic_id is None or table_id is None:
        return 'No topic_id or table_if found', 400
    msg_headers.update({'topic_id': topic_id, 'table_id': table_id})
    if any(key not in msg_headers for key in ['start_seq', 'data_encode', 'data_store', 'data_format']):
        return 'Xeed Header check error, something goeswrong', 400
    if msg_headers['data_store'] != 'body':
        content = request.data
    elif 'Content-Encoding' not in http_header_dict:
        if msg_headers['data_encode'] == 'flat':
            msg_headers['data_encode'] = 'gzip'
            content = gzip.compress(request.data)
        else:
            content = request.data
    else:
        if msg_headers['data_encode'] == 'flat':
            msg_headers['data_encode'] = 'gzip'
            content = request.data
        else:
            content = gzip.decompress(request.data)

    seeder.push_data(msg_headers, content, "pubsub", destination, topic_id, table_id, 0)
    return 'Data has been pushed to the destination', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))  # pragma: no cover