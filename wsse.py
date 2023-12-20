"""
Functions for WS-Security (WSSE) signing + encrypting

Code based on python-zeep & py-wsse
"""

import base64
import textwrap

from lxml import etree
from OpenSSL import crypto
import xmlsec

from constants import BASE64B, X509TOKEN, DS_NS, ENC_NS, ENV_NS, WSSE_NS, ATTACHMENT, C14N, WSU_NS
from xmlhelpers import ensure_id, ns
from hashing import generate_hash

def sign(envelope, doc_id, doc_hash, body, messaging, keyfile, certfile, password):
    header = envelope.find(ns(ENV_NS, 'Header'))
    security = header.find(ns(WSSE_NS, 'Security'))

    security_token = create_binary_security_token(certfile)
    security.insert(0, security_token)
    
    key = _sign_key(keyfile, certfile, password)

    # hax hax
    messaging_str = etree.tostring(messaging, pretty_print=True).decode('utf-8')
    # "proper" indention
    messaging_str = textwrap.indent(messaging_str, '    ')
    messaging_hash = generate_hash(etree.fromstring(messaging_str))

    messaging_id = messaging.get(etree.QName(WSU_NS, 'Id'))
    body_hash = generate_hash(body)
    body_id = body.get(etree.QName(WSU_NS, 'Id'))

    sig_info = signature_info(doc_id, doc_hash, body_id, body_hash, messaging_id, messaging_hash)
    #print(sig_info)

    ctx = xmlsec.SignatureContext()
    ctx.key = key

    sign = ctx.sign_binary(sig_info.encode('utf-8'), xmlsec.constants.TransformRsaSha256)
    signature_value = base64.b64encode(sign).decode('utf-8')
    #print(signature_value)

    key_info = etree.tostring(create_key_info_bst(security_token)).decode('utf-8')

    signature = """
<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
%s
<ds:SignatureValue>%s</ds:SignatureValue>
%s
</ds:Signature>
    """ % (sig_info, signature_value, key_info)

    security.insert(1, etree.fromstring(signature))

### HELPERS ###

def _sign_key(keyfile, certfile, password):
    key = xmlsec.Key.from_file(keyfile, xmlsec.KeyFormat.PEM, password)
    key.load_cert_from_file(certfile, xmlsec.KeyFormat.PEM)
    return key

def _add_ref(ref_id, transform, digest_value):
    if transform != ATTACHMENT:
        ref_id = '#' + ref_id

    return """
<ds:Reference URI="%s">
 <ds:Transforms>
  <ds:Transform Algorithm="%s"></ds:Transform>
 </ds:Transforms>
 <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>
 <ds:DigestValue>%s</ds:DigestValue>
</ds:Reference>""" % (ref_id, transform, digest_value)

def signature_info(doc_id, doc_hash, body_id, body_hash, messaging_id, messaging_hash):
    return """<ds:SignedInfo xmlns:ds="%s" xmlns:env="%s">
 <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#">
  <ec:InclusiveNamespaces xmlns:ec="http://www.w3.org/2001/10/xml-exc-c14n#" PrefixList="env"></ec:InclusiveNamespaces>
 </ds:CanonicalizationMethod>
 <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"></ds:SignatureMethod>%s%s%s
</ds:SignedInfo>""" % (
        DS_NS, ENV_NS,
        _add_ref(body_id, C14N, body_hash),
        _add_ref(messaging_id, C14N, messaging_hash),
        _add_ref(doc_id, ATTACHMENT, doc_hash)
    )

def add_data_reference(enc_key, enc_data):
    data_id = ensure_id(enc_data)
    ref_list = ensure_reference_list(enc_key)

    data_ref = etree.SubElement(ref_list, ns(ENC_NS, 'DataReference'))
    data_ref.set('URI', '#' + data_id)
    return data_ref

def ensure_reference_list(encrypted_key):
    ref_list = encrypted_key.find(ns(ENC_NS, 'ReferenceList'))
    if ref_list is None:
        ref_list = etree.SubElement(encrypted_key, ns(ENC_NS, 'ReferenceList'))
    return ref_list

def create_key_info_bst(security_token):
    key_info = etree.Element(ns(DS_NS, 'KeyInfo'), nsmap={'ds': DS_NS})

    sec_token_ref = etree.SubElement(key_info, ns(WSSE_NS, 'SecurityTokenReference'))
    sec_token_ref.set(ns(WSSE_NS, 'TokenType'), security_token.get('ValueType'))

    # reference BinarySecurityToken
    bst_id = ensure_id(security_token, 'BST')
    reference = etree.SubElement(sec_token_ref, ns(WSSE_NS, 'Reference'))
    reference.set('ValueType', security_token.get('ValueType'))
    reference.set('URI', '#%s' % bst_id)

    return key_info

def create_binary_security_token(certfile):
    node = etree.Element(ns(WSSE_NS, 'BinarySecurityToken'))
    node.set('EncodingType', BASE64B)
    node.set('ValueType', X509TOKEN)

    with open(certfile) as fh:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, fh.read())
        node.text = base64.b64encode(crypto.dump_certificate(crypto.FILETYPE_ASN1, cert))

    return node
