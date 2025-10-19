# Install new dependency
pip install pyyaml

# Use parallel mode with 5 threads (uses config.yml)
python script.py crawl

# Increase threads for faster crawling
python script.py crawl --threads 10

# Disable parallel mode (single-threaded)
python script.py crawl --sequential

# Crawl Custom threads with custom URL (overrides config)
python script.py crawl --threads 8 --url http://example.com/movies/

# Browse mode
# Start local server and open browser (default port 8000)
python script.py browse

# Use custom port
python script.py browse --port 8080


# Use custom config file
python script.py crawl --config my_config.yml

# Override specific settings
python script.py crawl --json my_data.json --html my_browser.html

