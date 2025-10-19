import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import json
import os
import argparse
import webbrowser
import yaml
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import time

# Setup logging
def setup_logging(log_level='INFO'):
    """Setup logging with both file and console handlers"""
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Create log filename with timestamp
    log_file = log_dir / f'crawler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Create logger
    logger = logging.getLogger('MovieCrawler')
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    logger.handlers = []
    
    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - [%(threadName)s] - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Logging initialized - Log file: {log_file}")
    return logger

# Load configuration
def load_config(config_file='config.yml'):
    """Load configuration from YAML file"""
    if not Path(config_file).exists():
        # Create default config
        default_config = {
            'crawler': {
                'base_url': 'http://103.145.232.246/Data/movies/',
                'timeout': 10,
                'max_retries': 3,
                'max_threads': 5,
                'parallel_enabled': True
            },
            'output': {
                'json_file': 'movie_tree.json',
                'html_file': 'movie_browser.html'
            },
            'logging': {
                'level': 'INFO',
                'log_dir': 'logs'
            }
        }
        
        with open(config_file, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        
        print(f"✨ Created default config file: {config_file}")
        return default_config
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config

class FolderCrawler:
    def __init__(self, base_url, config, logger):
        self.base_url = base_url
        self.config = config
        self.logger = logger
        self.tree = {}
        self.timeout = config.get('crawler', {}).get('timeout', 10)
        self.max_retries = config.get('crawler', {}).get('max_retries', 3)
        self.max_threads = config.get('crawler', {}).get('max_threads', 5)
        self.parallel_enabled = config.get('crawler', {}).get('parallel_enabled', True)
        self.stats = {'folders': 0, 'files': 0, 'errors': 0}
        self.stats_lock = Lock()
        self.start_time = None
        
    def crawl(self, url, path=[]):
        """Entry point for crawling - chooses parallel or sequential"""
        self.start_time = time.time()
        self.logger.info(f"Starting crawl with parallel={self.parallel_enabled}, max_threads={self.max_threads}")
        print(f"🚀 Starting crawl (Parallel: {self.parallel_enabled}, Threads: {self.max_threads})")
        
        if self.parallel_enabled:
            return self._crawl_parallel(url, path)
        else:
            return self._crawl_sequential(url, path)
    
    def _crawl_sequential(self, url, path=[], retry_count=0):
        """Sequential crawling (original single-threaded approach)"""
        try:
            self.logger.debug(f"Crawling URL: {url}")
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a')
            
            current_node = {
                'type': 'folder',
                'url': url,
                'children': {}
            }
            
            self.stats['folders'] += 1
            
            for link in links:
                href = link.get('href')
                if not href or href in ['../', '../', '/']:
                    continue
                
                name = unquote(href.strip('/'))
                full_url = urljoin(url, href)
                
                # Check if it's a folder (ends with /)
                if href.endswith('/'):
                    path_str = '/'.join(path + [name])
                    self.logger.info(f"📁 Crawling folder: {path_str}")
                    print(f"📁 Crawling: {path_str}")
                    current_node['children'][name] = self._crawl_sequential(full_url, path + [name])
                else:
                    # It's a file
                    self.stats['files'] += 1
                    file_size = self._get_file_info(link)
                    self.logger.debug(f"📄 Found file: {name} ({file_size or 'unknown size'})")
                    current_node['children'][name] = {
                        'type': 'file',
                        'url': full_url,
                        'size': file_size
                    }
            
            return current_node
            
        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout while crawling {url}")
            if retry_count < self.max_retries:
                self.logger.info(f"Retrying... (attempt {retry_count + 1}/{self.max_retries})")
                return self._crawl_sequential(url, path, retry_count + 1)
            self.stats['errors'] += 1
            return self._error_node(url, "Timeout")
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request error while crawling {url}: {e}")
            if retry_count < self.max_retries:
                self.logger.info(f"Retrying... (attempt {retry_count + 1}/{self.max_retries})")
                return self._crawl_sequential(url, path, retry_count + 1)
            self.stats['errors'] += 1
            return self._error_node(url, str(e))
            
        except Exception as e:
            self.logger.error(f"Unexpected error while crawling {url}: {e}", exc_info=True)
            self.stats['errors'] += 1
            return self._error_node(url, str(e))
    
    def _crawl_parallel(self, url, path=[]):
        """Parallel crawling using ThreadPoolExecutor"""
        return self._crawl_folder(url, path)
    
    def _crawl_folder(self, url, path=[], retry_count=0):
        """Crawl a single folder and submit child folders to thread pool"""
        try:
            self.logger.debug(f"Crawling URL: {url}")
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a')
            
            current_node = {
                'type': 'folder',
                'url': url,
                'children': {}
            }
            
            with self.stats_lock:
                self.stats['folders'] += 1
            
            # Separate folders and files
            folders_to_crawl = []
            files = {}
            
            for link in links:
                href = link.get('href')
                if not href or href in ['../', '../', '/']:
                    continue
                
                name = unquote(href.strip('/'))
                full_url = urljoin(url, href)
                
                if href.endswith('/'):
                    # It's a folder - add to list for parallel processing
                    folders_to_crawl.append((name, full_url, path + [name]))
                else:
                    # It's a file - process immediately
                    with self.stats_lock:
                        self.stats['files'] += 1
                    file_size = self._get_file_info(link)
                    self.logger.debug(f"📄 Found file: {name} ({file_size or 'unknown size'})")
                    files[name] = {
                        'type': 'file',
                        'url': full_url,
                        'size': file_size
                    }
            
            # Add files to current node
            current_node['children'].update(files)
            
            # Process folders in parallel if there are any
            if folders_to_crawl:
                with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                    future_to_folder = {
                        executor.submit(self._crawl_folder, full_url, folder_path): (name, full_url, folder_path)
                        for name, full_url, folder_path in folders_to_crawl
                    }
                    
                    for future in as_completed(future_to_folder):
                        name, full_url, folder_path = future_to_folder[future]
                        try:
                            path_str = '/'.join(folder_path)
                            self.logger.info(f"📁 Completed folder: {path_str}")
                            print(f"📁 Completed: {path_str}")
                            result = future.result()
                            current_node['children'][name] = result
                        except Exception as e:
                            self.logger.error(f"Error processing folder {name}: {e}", exc_info=True)
                            with self.stats_lock:
                                self.stats['errors'] += 1
                            current_node['children'][name] = self._error_node(full_url, str(e))
            
            return current_node
            
        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout while crawling {url}")
            if retry_count < self.max_retries:
                self.logger.info(f"Retrying... (attempt {retry_count + 1}/{self.max_retries})")
                time.sleep(1)  # Brief delay before retry
                return self._crawl_folder(url, path, retry_count + 1)
            with self.stats_lock:
                self.stats['errors'] += 1
            return self._error_node(url, "Timeout")
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request error while crawling {url}: {e}")
            if retry_count < self.max_retries:
                self.logger.info(f"Retrying... (attempt {retry_count + 1}/{self.max_retries})")
                time.sleep(1)
                return self._crawl_folder(url, path, retry_count + 1)
            with self.stats_lock:
                self.stats['errors'] += 1
            return self._error_node(url, str(e))
            
        except Exception as e:
            self.logger.error(f"Unexpected error while crawling {url}: {e}", exc_info=True)
            with self.stats_lock:
                self.stats['errors'] += 1
            return self._error_node(url, str(e))
    
    def _error_node(self, url, error_msg):
        """Create an error node"""
        return {
            'type': 'folder',
            'url': url,
            'children': {},
            'error': error_msg
        }
    
    def _get_file_info(self, link):
        """Extract file size if available"""
        text = link.parent.get_text() if link.parent else ""
        # Try to extract size from the listing
        parts = text.split()
        for i, part in enumerate(parts):
            if any(unit in part.upper() for unit in ['KB', 'MB', 'GB', 'TB']):
                return part
        return None
    
    def save_json(self, filename):
        """Save tree structure to JSON"""
        try:
            self.logger.info(f"Saving JSON to {filename}")
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.tree, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✅ Tree saved to {filename}")
            print(f"✅ Tree saved to {filename}")
        except Exception as e:
            self.logger.error(f"Failed to save JSON: {e}", exc_info=True)
            raise
    
    def generate_html(self, filename, json_file):
        """Generate interactive HTML viewer"""
        try:
            self.logger.info(f"Generating HTML file: {filename}")
            html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Movie Folder Browser</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .search-box {
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 2px solid #e9ecef;
        }
        
        .search-input {
            width: 100%;
            padding: 15px;
            font-size: 16px;
            border: 2px solid #667eea;
            border-radius: 5px;
            outline: none;
            transition: all 0.3s;
        }
        
        .search-input:focus {
            border-color: #764ba2;
            box-shadow: 0 0 0 3px rgba(118, 75, 162, 0.1);
        }
        
        .breadcrumb {
            padding: 15px 20px;
            background: #fff;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .breadcrumb-item {
            color: #667eea;
            text-decoration: none;
            padding: 5px 10px;
            border-radius: 3px;
            transition: all 0.2s;
            cursor: pointer;
        }
        
        .breadcrumb-item:hover {
            background: #f8f9fa;
        }
        
        .breadcrumb-separator {
            margin: 0 5px;
            color: #6c757d;
        }
        
        .content {
            padding: 20px;
            max-height: 600px;
            overflow-y: auto;
        }
        
        .folder, .file {
            padding: 12px 15px;
            margin: 5px 0;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .folder:hover, .file:hover {
            background: #f8f9fa;
            transform: translateX(5px);
        }
        
        .folder {
            background: #e7f3ff;
            border-left: 4px solid #667eea;
        }
        
        .file {
            background: #fff;
            border-left: 4px solid #28a745;
        }
        
        .icon {
            font-size: 1.5em;
        }
        
        .name {
            flex: 1;
            font-weight: 500;
        }
        
        .size {
            color: #6c757d;
            font-size: 0.9em;
        }
        
        .no-results {
            text-align: center;
            padding: 40px;
            color: #6c757d;
        }
        
        .stats {
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            display: flex;
            justify-content: space-around;
            text-align: center;
        }
        
        .stat-item {
            flex: 1;
        }
        
        .stat-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #6c757d;
            font-size: 0.9em;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #667eea;
            font-size: 1.2em;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 Movie Folder Browser</h1>
            <p>Browse and search your movie collection</p>
        </div>
        
        <div class="search-box">
            <input type="text" class="search-input" id="searchInput" placeholder="Search for movies or folders...">
        </div>
        
        <div class="breadcrumb" id="breadcrumb">
            <span class="breadcrumb-item" onclick="navigateTo([])">🏠 Home</span>
        </div>
        
        <div class="content" id="content">
            <div class="loading">Loading movie data...</div>
        </div>
        
        <div class="stats" id="stats">
            <div class="stat-item">
                <div class="stat-value" id="folderCount">0</div>
                <div class="stat-label">Folders</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" id="fileCount">0</div>
                <div class="stat-label">Files</div>
            </div>
        </div>
    </div>
    
    <script>
        let treeData = null;
        let currentPath = [];
        let allItems = [];
        
        // Load JSON file
        fetch('JSON_FILE_PLACEHOLDER')
            .then(response => response.json())
            .then(data => {
                treeData = data;
                initializeSearch();
                navigateTo([]);
            })
            .catch(error => {
                document.getElementById('content').innerHTML = 
                    '<div class="no-results">Error loading movie data: ' + error.message + '</div>';
            });
        
        function initializeSearch() {
            allItems = [];
            flattenTree(treeData, []);
        }
        
        function flattenTree(node, path) {
            if (node.children) {
                for (const [name, child] of Object.entries(node.children)) {
                    const itemPath = [...path, name];
                    allItems.push({
                        name: name,
                        path: itemPath,
                        type: child.type,
                        url: child.url,
                        size: child.size
                    });
                    
                    if (child.type === 'folder') {
                        flattenTree(child, itemPath);
                    }
                }
            }
        }
        
        function navigateTo(path) {
            currentPath = path;
            renderBreadcrumb();
            renderContent();
        }
        
        function renderBreadcrumb() {
            const breadcrumb = document.getElementById('breadcrumb');
            let html = '<span class="breadcrumb-item" onclick="navigateTo([])">🏠 Home</span>';
            
            currentPath.forEach((item, index) => {
                const partialPath = currentPath.slice(0, index + 1);
                html += '<span class="breadcrumb-separator">›</span>';
                html += `<span class="breadcrumb-item" onclick='navigateTo(${JSON.stringify(partialPath)})'>${item}</span>`;
            });
            
            breadcrumb.innerHTML = html;
        }
        
        function renderContent() {
            const content = document.getElementById('content');
            let node = treeData;
            
            for (const segment of currentPath) {
                node = node.children[segment];
            }
            
            if (!node || !node.children) {
                content.innerHTML = '<div class="no-results">No items found</div>';
                return;
            }
            
            const items = Object.entries(node.children);
            const folders = items.filter(([_, item]) => item.type === 'folder');
            const files = items.filter(([_, item]) => item.type === 'file');
            
            let html = '';
            
            folders.forEach(([name, item]) => {
                html += `
                    <div class="folder" onclick='navigateTo(${JSON.stringify([...currentPath, name])})'>
                        <span class="icon">📁</span>
                        <span class="name">${name}</span>
                    </div>
                `;
            });
            
            files.forEach(([name, item]) => {
                html += `
                    <div class="file" onclick='window.open("${item.url}", "_blank")'>
                        <span class="icon">🎬</span>
                        <span class="name">${name}</span>
                        ${item.size ? `<span class="size">${item.size}</span>` : ''}
                    </div>
                `;
            });
            
            content.innerHTML = html || '<div class="no-results">No items found</div>';
            updateStats();
        }
        
        function updateStats() {
            let folderCount = 0;
            let fileCount = 0;
            
            function count(node) {
                if (node.children) {
                    for (const child of Object.values(node.children)) {
                        if (child.type === 'folder') {
                            folderCount++;
                            count(child);
                        } else {
                            fileCount++;
                        }
                    }
                }
            }
            
            count(treeData);
            document.getElementById('folderCount').textContent = folderCount;
            document.getElementById('fileCount').textContent = fileCount;
        }
        
        function searchItems(query) {
            if (!query) {
                renderContent();
                return;
            }
            
            const content = document.getElementById('content');
            const results = allItems.filter(item => 
                item.name.toLowerCase().includes(query.toLowerCase())
            );
            
            if (results.length === 0) {
                content.innerHTML = '<div class="no-results">No results found</div>';
                return;
            }
            
            let html = '';
            results.forEach(item => {
                const pathStr = item.path.join(' › ');
                const icon = item.type === 'folder' ? '📁' : '🎬';
                const className = item.type;
                
                if (item.type === 'folder') {
                    html += `
                        <div class="${className}" onclick='navigateTo(${JSON.stringify(item.path)})'>
                            <span class="icon">${icon}</span>
                            <span class="name">${item.name}</span>
                            <span class="size" style="flex: 0 0 auto; max-width: 60%;">${pathStr}</span>
                        </div>
                    `;
                } else {
                    html += `
                        <div class="${className}" onclick='window.open("${item.url}", "_blank")'>
                            <span class="icon">${icon}</span>
                            <span class="name">${item.name}</span>
                            <span class="size" style="flex: 0 0 auto; max-width: 60%;">${pathStr}</span>
                        </div>
                    `;
                }
            });
            
            content.innerHTML = html;
        }
        
        document.getElementById('searchInput').addEventListener('input', (e) => {
            searchItems(e.target.value);
        });
    </script>
</body>
</html>'''
            
            # Replace placeholder with actual JSON file path
            html_content = html_content.replace('JSON_FILE_PLACEHOLDER', json_file)
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            self.logger.info(f"✅ HTML viewer saved to {filename}")
            print(f"✅ HTML viewer saved to {filename}")
        except Exception as e:
            self.logger.error(f"Failed to generate HTML: {e}", exc_info=True)
            raise
    
    def print_stats(self):
        """Print crawling statistics"""
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        
        self.logger.info("=" * 50)
        self.logger.info("Crawling Statistics:")
        self.logger.info(f"  Folders found: {self.stats['folders']}")
        self.logger.info(f"  Files found: {self.stats['files']}")
        self.logger.info(f"  Errors encountered: {self.stats['errors']}")
        self.logger.info(f"  Time elapsed: {elapsed_time:.2f} seconds")
        if self.stats['folders'] > 0:
            self.logger.info(f"  Average: {elapsed_time/self.stats['folders']:.2f} sec/folder")
        self.logger.info("=" * 50)
        
        print("\n" + "=" * 50)
        print("📊 Crawling Statistics:")
        print(f"  📁 Folders: {self.stats['folders']}")
        print(f"  📄 Files: {self.stats['files']}")
        print(f"  ❌ Errors: {self.stats['errors']}")
        print(f"  ⏱️  Time: {elapsed_time:.2f} seconds")
        if self.stats['folders'] > 0:
            print(f"  ⚡ Speed: {elapsed_time/self.stats['folders']:.2f} sec/folder")
        print("=" * 50)

def crawl_mode(config, logger, base_url=None, json_file=None, html_file=None):
    """Crawl mode: Crawl the website and generate files"""
    logger.info("🕷️  Starting crawl mode...")
    
    url = base_url or config['crawler']['base_url']
    json_path = json_file or config['output']['json_file']
    html_path = html_file or config['output']['html_file']
    
    logger.info(f"Target URL: {url}")
    print(f"🎯 Target URL: {url}")
    
    crawler = FolderCrawler(url, config, logger)
    crawler.tree = crawler.crawl(url)
    
    logger.info("💾 Saving results...")
    print("\n💾 Saving results...")
    crawler.save_json(json_path)
    crawler.generate_html(html_path, json_path)
    
    crawler.print_stats()
    logger.info("✅ Crawl completed successfully!")
    print("\n✅ Crawl completed successfully!")

def browse_mode(config, logger, json_file=None, html_file=None, port=8000):
    """Browse mode: Launch HTML viewer using existing JSON with local HTTP server"""
    import http.server
    import socketserver
    import threading
    
    logger.info("🌐 Starting browse mode...")
    print("🌐 Starting browse mode...")
    
    json_path = json_file or config['output']['json_file']
    html_path = html_file or config['output']['html_file']
    
    # Check if JSON file exists
    if not Path(json_path).exists():
        error_msg = f"JSON file not found: {json_path}"
        logger.error(error_msg)
        print(f"❌ Error: {error_msg}")
        print(f"Please run in crawl mode first: python script.py crawl")
        return
    
    logger.info(f"Using JSON file: {json_path}")
    
    # Check if HTML file exists, generate if not
    if not Path(html_path).exists():
        logger.info(f"HTML file not found, generating {html_path}...")
        print(f"📄 HTML file not found, generating {html_path}...")
        crawler = FolderCrawler("", config, logger)
        crawler.generate_html(html_path, json_path)
    
    # Start local HTTP server
    class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            # Only log errors
            if args[1] != '200':
                logger.debug(f"{self.address_string()} - {format % args}")
    
    # Find available port
    original_port = port
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            Handler = QuietHTTPRequestHandler
            with socketserver.TCPServer(("", port), Handler) as httpd:
                server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                server_thread.start()
                
                url = f"http://localhost:{port}/{html_path}"
                logger.info(f"🚀 Starting local server on port {port}")
                print(f"🚀 Local server running at http://localhost:{port}")
                print(f"📄 Opening {html_path} in browser...")
                print(f"\n✨ Press Ctrl+C to stop the server\n")
                
                # Open browser
                webbrowser.open(url)
                logger.info("✅ Browser launched!")
                
                try:
                    # Keep server running
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    logger.info("Server stopped by user")
                    print("\n👋 Server stopped")
                    httpd.shutdown()
                    break
                    
        except OSError as e:
            if "Address already in use" in str(e):
                port += 1
                if attempt < max_attempts - 1:
                    logger.warning(f"Port {port-1} in use, trying {port}")
                    continue
                else:
                    logger.error(f"Could not find available port after {max_attempts} attempts")
                    print(f"❌ Error: Ports {original_port}-{port} are all in use")
                    return
            else:
                raise

def main():
    parser = argparse.ArgumentParser(
        description='Movie Folder Browser - Crawl and browse movie directories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Crawl the website (parallel mode by default)
  python script.py crawl
  
  # Crawl with custom URL
  python script.py crawl --url http://example.com/movies/
  
  # Crawl in sequential mode (single-threaded)
  python script.py crawl --sequential
  
  # Crawl with custom thread count
  python script.py crawl --threads 10
  
  # Browse existing data (opens in browser)
  python script.py browse
  
  # Use custom config file
  python script.py crawl --config my_config.yml
        '''
    )
    
    parser.add_argument('mode', choices=['crawl', 'browse'], 
                       help='Mode: crawl (scrape website) or browse (open HTML viewer)')
    parser.add_argument('--config', default='config.yml',
                       help='Configuration file (default: config.yml)')
    parser.add_argument('--url', 
                       help='Base URL to crawl (overrides config)')
    parser.add_argument('--json',
                       help='JSON output/input file (overrides config)')
    parser.add_argument('--html',
                       help='HTML output file (overrides config)')
    parser.add_argument('--threads', type=int,
                       help='Max number of parallel threads (overrides config)')
    parser.add_argument('--sequential', action='store_true',
                       help='Disable parallel crawling (use single thread)')
    parser.add_argument('--port', type=int, default=8000,
                       help='Port for local HTTP server in browse mode (default: 8000)')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Override config with command-line arguments
    if args.threads:
        config['crawler']['max_threads'] = args.threads
    if args.sequential:
        config['crawler']['parallel_enabled'] = False
    
    # Setup logging
    log_level = config.get('logging', {}).get('level', 'INFO')
    logger = setup_logging(log_level)
    
    logger.info(f"Configuration loaded from {args.config}")
    logger.info(f"Mode: {args.mode}")
    
    try:
        if args.mode == 'crawl':
            crawl_mode(config, logger, args.url, args.json, args.html)
        elif args.mode == 'browse':
            browse_mode(config, logger, args.json, args.html, args.port)
    except KeyboardInterrupt:
        logger.warning("Operation cancelled by user")
        print("\n⚠️  Operation cancelled by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()