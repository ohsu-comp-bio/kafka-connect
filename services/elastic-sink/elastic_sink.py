from kafka import KafkaConsumer
from elasticsearch import Elasticsearch
from elasticsearch import ConflictError
import json
import argparse
import logging
import sys

logger = logging.getLogger('elastic_sink')


def get_id(value):
    """ get the md5 checksum as the id """
    for checksum in value['checksums']:
        if checksum['type'] == 'md5':
            return checksum['checksum']


class ElasticHandler(object):

    """Maintain DOS key/value in Elastic """

    def __init__(self,
                 elastic_url=None,
                 dry_run=False):
        super(ElasticHandler, self).__init__()
        self.elastic_url = elastic_url
        self.dry_run = dry_run
        self._es = Elasticsearch([self.elastic_url])

    def on_any_event(self, key, value):
        try:
            self.process(key, value)
        except Exception as e:
            logger.exception(e)
            logger.error(key)
            logger.error(value)

    def process(self, key, value):
        """
        decorate metadata, insert or update
        """
        value = self.decorate_metadata(key, value)
        try:
            self.to_elastic(key, value)
        except ConflictError as e:
            self.update_elastic(key, value)

    def decorate_metadata(self, key, value):
        """ update dos user_metadata with complete meta data """
        if 'user_metadata' in value and \
                'patient_id' in value['user_metadata'] and \
                'library_id' in value['user_metadata']:
            es = self._es
            patient_id = value['user_metadata']['patient_id']
            library_id = value['user_metadata']['library_id']
            res = es.search(index='dos', doc_type='meta',
                            q='patient_id:\"{}\" AND '
                            'library_id:\"{}\"'
                            .format(patient_id, library_id))
            doc = res['hits']['hits'][0]
            meta = doc['_source']
            user_metadata = value['user_metadata']
            for key in meta.keys():
                if key not in user_metadata:
                    user_metadata[key] = meta[key]
        return value

    def update_elastic(self, key, value):
        """ update dict to elastic"""
        es = self._es
        doc = es.get(index='dos', doc_type='dos', id=get_id(value))
        existing_urls = doc['_source']['urls']
        new_urls = value['urls']
        existing_metadata = doc['_source']['user_metadata']
        new_metadata = value['user_metadata']
        new_metadata.update(existing_metadata)
        es.update(index='dos', doc_type='dos',
                  id=get_id(value),
                  body={
                    'doc': {
                        'urls': existing_urls + new_urls,
                        'user_metadata': new_metadata,
                        }
                  })

    def to_elastic(self, key, value):
        """ write dict to elastic"""
        if self.dry_run:
            logger.debug(key)
            logger.debug(value)
            return
        es = self._es
        if key.startswith('ObjectRemoved'):
            logger.debug(key)
            url = key.split('~')[1]
            res = es.search(index='dos', doc_type='dos',
                            q='url:\"{}\"'.format(url))
            for doc in res['hits']['hits']:
                del_rsp = es.delete(index='dos', doc_type='dos', id=doc['_id'])
                logger.debug(del_rsp)
        else:
            es.create(index='dos', doc_type='dos',
                      id=get_id(value), body=value)


if __name__ == "__main__":

    argparser = argparse.ArgumentParser(
        description='Consume events from topic, populate elastic')

    argparser.add_argument('--kafka_topic', '-kt',
                           help='''kafka_topic''',
                           default='dos-topic')

    argparser.add_argument('--kafka_bootstrap', '-kb',
                           help='''kafka host:port''',
                           default='localhost:9092')

    argparser.add_argument('--dry_run', '-d',
                           help='''dry run''',
                           default=False,
                           action='store_true')

    argparser.add_argument('--elastic_url', '-e',
                           help='''elasticsearch endpoint''',
                           default='localhost:9200')

    argparser.add_argument('--group_id', '-g',
                           help='''kafka consumer group''',
                           default='elastic_sink')

    argparser.add_argument('--enable_auto_commit', '-ac',
                           help='''commit offsets ''',
                           default=False,
                           action='store_true')

    argparser.add_argument('--no_tls',
                           help='kafka connection plaintext? default: False',
                           default=False,
                           action='store_true')

    argparser.add_argument('--ssl_cafile',
                           help='server CA pem file',
                           default='/client-certs/CARoot.pem')

    argparser.add_argument('--ssl_certfile',
                           help='client certificate pem file',
                           default='/client-certs/certificate.pem')

    argparser.add_argument('--ssl_keyfile',
                           help='client private key pem file',
                           default='/client-certs/key.pem')

    argparser.add_argument("-v", "--verbose", help="increase output verbosity",
                           default=False,
                           action="store_true")

    args = argparser.parse_args()

    if args.verbose:
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    logger = logging.getLogger(__name__)

    event_handler = ElasticHandler(
        elastic_url=args.elastic_url,
        dry_run=args.dry_run,
    )

    # To consume latest messages and auto-commit offsets
    if not args.no_tls:
        consumer = KafkaConsumer(args.kafka_topic,
                                 group_id=args.group_id,
                                 bootstrap_servers=[args.kafka_bootstrap],
                                 # consumer_timeout_ms=10000,
                                 auto_offset_reset='earliest',
                                 enable_auto_commit=args.enable_auto_commit,
                                 security_protocol='SSL',
                                 ssl_check_hostname=False,
                                 ssl_cafile=args.ssl_cafile,
                                 ssl_certfile=args.ssl_certfile,
                                 ssl_keyfile=args.ssl_keyfile)
    else:
        consumer = KafkaConsumer(args.kafka_topic,
                                 group_id=args.group_id,
                                 bootstrap_servers=[args.kafka_bootstrap],
                                 # consumer_timeout_ms=10000,
                                 auto_offset_reset='earliest',
                                 enable_auto_commit=args.enable_auto_commit)

    for message in consumer:
        # message value and key are raw bytes -- decode if necessary!
        # e.g., for unicode: `message.value.decode('utf-8')`
        # logger.debug("%s:%d:%d: payload=%s" % (message.topic,
        #                                        message.partition,
        #                                        message.offset,
        #                                        json.loads(message.value)))
        sys.stderr.write('.')
        sys.stderr.flush()
        event_handler.on_any_event(message.key, json.loads(message.value))

