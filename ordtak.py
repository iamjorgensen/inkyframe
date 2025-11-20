import requests

# ZenQuotes API-endepunkt for tilfeldig sitat
url = "https://zenquotes.io/api/random"

# Send GET-forespørsel
response = requests.get(url)

# Sjekk status og hent data
if response.status_code == 200:
    data = response.json()
    quote = data[0]['q']  # selve sitatet
    author = data[0]['a']  # forfatter
    print(f'"{quote}" - {author}')
else:
    print("Kunne ikke hente sitat. Statuskode:", response.status_code)