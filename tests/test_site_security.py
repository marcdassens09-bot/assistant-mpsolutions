import unittest
from unittest.mock import patch

import hardened_app  # active le filtre renforce
import website_app as w


class TestSiteSecurity(unittest.TestCase):
    def assertBlocked(self, value):
        with self.assertRaises(w.SiteSecurityError):
            w._normaliser_url(value)

    def test_private_literal_ipv4_blocked(self):
        for url in [
            'http://127.0.0.1',
            'http://10.0.0.1',
            'http://172.16.0.1',
            'http://192.168.1.1',
            'http://169.254.169.254',
            'http://0.0.0.0',
        ]:
            with self.subTest(url=url):
                self.assertBlocked(url)

    def test_private_literal_ipv6_blocked(self):
        for url in ['http://[::1]', 'http://[fc00::1]', 'http://[fe80::1]']:
            with self.subTest(url=url):
                self.assertBlocked(url)

    def test_bad_scheme_userinfo_and_ports_blocked(self):
        for url in [
            'file:///etc/passwd',
            'ftp://example.com/file',
            'http://user:pass@example.com',
            'http://example.com:8080',
            'https://example.com:444',
        ]:
            with self.subTest(url=url):
                self.assertBlocked(url)

    def test_public_url_normalized(self):
        self.assertEqual(w._normaliser_url('example.com'), 'https://example.com/')
        self.assertEqual(w._normaliser_url('https://example.com/path?q=1#frag'), 'https://example.com/path?q=1')

    @patch('website_app.socket.getaddrinfo')
    def test_dns_private_blocked(self, gai):
        gai.return_value = [(2, 1, 6, '', ('127.0.0.1', 443))]
        with self.assertRaises(w.SiteSecurityError):
            w._resolve_public_ip('example.com', 443)

    @patch('website_app.socket.getaddrinfo')
    def test_dns_mixed_public_private_blocked(self, gai):
        gai.return_value = [
            (2, 1, 6, '', ('93.184.216.34', 443)),
            (2, 1, 6, '', ('10.0.0.2', 443)),
        ]
        with self.assertRaises(w.SiteSecurityError):
            w._resolve_public_ip('example.com', 443)

    @patch('website_app._open_once')
    def test_cross_domain_redirect_blocked(self, opened):
        opened.return_value = {'redirect': 'https://evil.example/', 'status': 302}
        with self.assertRaises(w.SiteSecurityError):
            w._fetch_public_html('https://example.com/')

    @patch('website_app._open_once')
    def test_same_domain_redirect_allowed(self, opened):
        opened.side_effect = [
            {'redirect': 'https://www.example.com/new', 'status': 301},
            {'html': '<html><body>ok</body></html>', 'status': 200},
        ]
        final_url, html = w._fetch_public_html('https://example.com/')
        self.assertEqual(final_url, 'https://www.example.com/new')
        self.assertIn('ok', html)

    @patch('website_app._open_once')
    def test_redirect_loop_limited(self, opened):
        opened.return_value = {'redirect': '/again', 'status': 302}
        with self.assertRaises(w.SiteSecurityError):
            w._fetch_public_html('https://example.com/')
        self.assertEqual(opened.call_count, w.MAX_REDIRECTS + 1)

    def test_visible_text_removes_active_content_and_truncates(self):
        html = '<title>Entreprise</title><script>IGNORE ME</script><style>HIDE</style><body>Visible service</body>'
        out = w._extract_visible_text(html)
        self.assertIn('Visible service', out['text'])
        self.assertNotIn('IGNORE ME', out['text'])
        self.assertNotIn('HIDE', out['text'])
        self.assertLessEqual(len(out['text']), w.MAX_EXTRACTED_TEXT)

    def test_security_limits_are_present(self):
        self.assertLessEqual(w.MAX_SITE_BYTES, 512 * 1024)
        self.assertLessEqual(w.MAX_REDIRECTS, 3)
        self.assertLessEqual(w.FETCH_TIMEOUT, 6)
        self.assertLessEqual(w.MAX_EXTRACTED_TEXT, 14000)


if __name__ == '__main__':
    unittest.main()
