import re

# Read backup file
with open('templates/newsclip/client_news.html.backup', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Add spaces around == in Django if tags  
content = re.sub(r'({% if \w+)=="', r'\1 == "', content)
content = re.sub(r'=="(\w+)( %}|"\s*%})', r'== "\1"\2', content)
content = re.sub(r'({% if \w+)==(\w+)\s*%}', r'\1 == \2 %}', content)

# Fix 2: Chart.js - remove spaces before | in filters
content = content.replace('{{ daily_labels_json| safe }}', '{{ daily_labels_json|safe }}')
content = content.replace('{{ daily_counts_json| safe }}', '{{ daily_counts_json|safe }}')
content = content.replace('{{ source_labels_json| safe }}', '{{ source_labels_json|safe }}')
content = content.replace('{{ source_counts_json| safe }}', '{{ source_counts_json|safe }}')

# Fix 3: fetch button - add .json() parsing
old_fetch = '''        fetch("{% url 'fetch_news' client.id %}", {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
          .then(response => {
            overlay.style.display = 'none';
            btnFetch.disabled = false;
            if (response.redirected) {
              window.location.href = response.url;
            } else {
              window.location.reload();
            }
          })'''

new_fetch = '''        fetch("{% url 'fetch_news' client.id %}", {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
          .then(response => response.json())
          .then(data => {
            overlay.style.display = 'none';
            btnFetch.disabled = false;
            if (data.status === 'ok') {
              alert(data.message);
              window.location.reload();
            } else {
              alert('Erro: ' + data.message);
            }
          })'''

content = content.replace(old_fetch, new_fetch)

# Write fixed content
with open('templates/newsclip/client_news.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ All fixes applied!")
