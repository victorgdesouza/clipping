
from django.test import TestCase
 
# Create your tests here.
from newsclip.templatetags.source_extras import domain


class DomainFilterTests(TestCase):
    def test_domain_filter_removes_www_prefix(self):
        """domain filter deve extrair o host sem o prefixo www."""
        url = "https://www.exemplo.com/algum"
        self.assertEqual(domain(url), "exemplo.com")
 

