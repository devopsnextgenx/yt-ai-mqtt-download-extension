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
import re

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
                    file_info = self._get_file_info(link)
                    self.logger.debug(f"📄 Found file: {name} ({file_info.get('size') or 'unknown size'}, {file_info.get('last_modified') or 'no date'})")
                    current_node['children'][name] = {
                        'type': 'file',
                        'url': full_url,
                        'size': file_info.get('size'),
                        'last_modified': file_info.get('last_modified')
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
                    file_info = self._get_file_info(link)
                    self.logger.debug(f"📄 Found file: {name} ({file_info.get('size') or 'unknown size'}, {file_info.get('last_modified') or 'no date'})")
                    files[name] = {
                        'type': 'file',
                        'url': full_url,
                        'size': file_info.get('size'),
                        'last_modified': file_info.get('last_modified')
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
        """Extract file size and last modified date if available"""
        info = {'size': None, 'last_modified': None}
        
        # Get the text from the parent row (usually <tr> or <pre>)
        text = link.parent.get_text() if link.parent else ""
        
        # Try to extract size from the listing
        parts = text.split()
        for i, part in enumerate(parts):
            if any(unit in part.upper() for unit in ['KB', 'MB', 'GB', 'TB']):
                info['size'] = part
                break
        
        # Try to extract date and time (common Apache/nginx format)
        # Formats: "2024-01-15 14:30" or "15-Jan-2024 14:30" or "01/15/2024 02:30 PM"
        try:
            # Look for date patterns in the text
            # Pattern 1: YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS
            date_pattern1 = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)'
            # Pattern 2: DD-Mon-YYYY HH:MM
            date_pattern2 = r'(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})'
            # Pattern 3: MM/DD/YYYY HH:MM AM/PM
            date_pattern3 = r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?:\s+[AP]M)?)'
            # Pattern 4: DD/MM/YYYY HH:MM
            date_pattern4 = r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})'
            
            for pattern in [date_pattern1, date_pattern2, date_pattern3, date_pattern4]:
                match = re.search(pattern, text)
                if match:
                    info['last_modified'] = match.group(1).strip()
                    break
        except Exception as e:
            self.logger.debug(f"Could not parse date from: {text[:100]}")
        
        return info
    
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
    <title>🎬 Movie Folder Browser</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
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
        
        .header p {
            opacity: 0.9;
            font-size: 1.1em;
        }
        
        .controls {
            padding: 20px 30px;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .search-box {
            flex: 1;
            min-width: 250px;
            position: relative;
        }
        
        .search-box input {
            width: 100%;
            padding: 12px 40px 12px 15px;
            border: 2px solid #dee2e6;
            border-radius: 8px;
            font-size: 1em;
            transition: all 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .search-icon {
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: #6c757d;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 500;
        }
        
        .btn-primary {
            background: #667eea;
            color: white;
        }
        
        .btn-primary:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }
        
        .content {
            padding: 30px;
        }
        
        .tree {
            font-family: 'Courier New', monospace;
            line-height: 1.6;
        }
        
        .folder, .file {
            padding: 8px 12px;
            margin: 2px 0;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .folder:hover, .file:hover {
            background: #f8f9fa;
        }
        
        .folder {
            font-weight: 600;
            color: #495057;
        }
        
        .file {
            color: #6c757d;
        }
        
        .file-info {
            margin-left: auto;
            font-size: 0.85em;
            color: #868e96;
            display: flex;
            gap: 15px;
        }
        
        .file-size {
            min-width: 70px;
            text-align: right;
        }
        
        .file-date {
            min-width: 130px;
            text-align: right;
        }
        
        .folder.collapsed > .children {
            display: none;
        }
        
        .children {
            margin-left: 25px;
            border-left: 2px solid #e9ecef;
            padding-left: 10px;
        }
        
        .icon {
            font-size: 1.2em;
            width: 20px;
            text-align: center;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .stat-label {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .loading {
            text-align: center;
            padding: 60px;
            color: #6c757d;
            font-size: 1.2em;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
        }
        
        .breadcrumb {
            padding: 15px 30px;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            font-size: 0.9em;
        }
        
        .breadcrumb a {
            color: #667eea;
            text-decoration: none;
            margin: 0 5px;
        }
        
        .breadcrumb a:hover {
            text-decoration: underline;
        }
        
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }
            
            .controls {
                flex-direction: column;
            }
            
            .search-box {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 Movie Folder Browser</h1>
            <p>Browse and search your movie collection</p>
        </div>
        
        <div class="breadcrumb">
            <span>📍</span>
            <a href="#" id="homeBtn">🏠 Home</a>
        </div>
        
        <div class="controls">
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search for movies, folders...">
                <span class="search-icon">🔍</span>
            </div>
            <button class="btn btn-primary" id="expandAll">Expand All</button>
            <button class="btn btn-primary" id="collapseAll">Collapse All</button>
        </div>
        
        <div class="content">
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value" id="folderCount">0</div>
                    <div class="stat-label">Folders</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="fileCount">0</div>
                    <div class="stat-label">Files</div>
                </div>
            </div>
            
            <div class="loading" id="loading">Loading movie data...</div>
            <div id="treeContainer"></div>
        </div>
    </div>
    
    <script>
        let treeData = null;
        let stats = { folders: 0, files: 0 };
        
        // Load JSON data
        async function loadData() {
            try {
                const response = await fetch('JSON_FILE_PLACEHOLDER');
                treeData = await response.json();
                document.getElementById('loading').style.display = 'none';
                renderTree(treeData);
                updateStats();
            } catch (error) {
                document.getElementById('loading').innerHTML = 
                    `<div class="error">❌ Error loading data: ${error.message}</div>`;
            }
        }
        
        function renderTree(data, container = null, level = 0) {
            if (!container) {
                container = document.getElementById('treeContainer');
                container.innerHTML = '';
            }
            
            if (!data || !data.children) return;
            
            const entries = Object.entries(data.children).sort((a, b) => {
                const aIsFolder = a[1].type === 'folder';
                const bIsFolder = b[1].type === 'folder';
                if (aIsFolder && !bIsFolder) return -1;
                if (!aIsFolder && bIsFolder) return 1;
                return a[0].localeCompare(b[0]);
            });
            
            entries.forEach(([name, node]) => {
                if (node.type === 'folder') {
                    stats.folders++;
                    const folderDiv = document.createElement('div');
                    folderDiv.className = 'folder';
                    
                    const folderHeader = document.createElement('div');
                    folderHeader.style.display = 'flex';
                    folderHeader.style.alignItems = 'center';
                    folderHeader.style.gap = '8px';
                    folderHeader.innerHTML = `
                        <span class="icon">📁</span>
                        <span>${name}</span>
                    `;
                    
                    const childrenDiv = document.createElement('div');
                    childrenDiv.className = 'children';
                    
                    folderHeader.onclick = (e) => {
                        e.stopPropagation();
                        folderDiv.classList.toggle('collapsed');
                        folderHeader.querySelector('.icon').textContent = 
                            folderDiv.classList.contains('collapsed') ? '📁' : '📂';
                    };
                    
                    folderDiv.appendChild(folderHeader);
                    folderDiv.appendChild(childrenDiv);
                    container.appendChild(folderDiv);
                    
                    renderTree(node, childrenDiv, level + 1);
                } else {
                    stats.files++;
                    const fileDiv = document.createElement('div');
                    fileDiv.className = 'file';
                    
                    const fileInfoHtml = `
                        <div class="file-info">
                            ${node.size ? `<span class="file-size">${node.size}</span>` : ''}
                            ${node.last_modified ? `<span class="file-date">📅 ${node.last_modified}</span>` : ''}
                        </div>
                    `;
                    
                    fileDiv.innerHTML = `
                        <span class="icon">📄</span>
                        <span>${name}</span>
                        ${fileInfoHtml}
                    `;
                    
                    fileDiv.onclick = () => {
                        window.open(node.url, '_blank');
                    };
                    
                    container.appendChild(fileDiv);
                }
            });
        }
        
        function updateStats() {
            document.getElementById('folderCount').textContent = stats.folders;
            document.getElementById('fileCount').textContent = stats.files;
        }
        
        function expandAll() {
            document.querySelectorAll('.folder.collapsed').forEach(folder => {
                folder.classList.remove('collapsed');
                folder.querySelector('.icon').textContent = '📂';
            });
        }
        
        function collapseAll() {
            document.querySelectorAll('.folder').forEach(folder => {
                folder.classList.add('collapsed');
                folder.querySelector('.icon').textContent = '📁';
            });
        }
        
        function search(query) {
            stats = { folders: 0, files: 0 };
            const container = document.getElementById('treeContainer');
            
            if (!query.trim()) {
                renderTree(treeData);
                updateStats();
                return;
            }
            
            container.innerHTML = '';
            searchTree(treeData, query.toLowerCase(), container);
            updateStats();
        }
        
        function searchTree(data, query, container) {
            if (!data || !data.children) return;
            
            Object.entries(data.children).forEach(([name, node]) => {
                if (name.toLowerCase().includes(query)) {
                    if (node.type === 'folder') {
                        stats.folders++;
                        const folderDiv = document.createElement('div');
                        folderDiv.className = 'folder';
                        folderDiv.innerHTML = `
                            <span class="icon">📂</span>
                            <span>${name}</span>
                        `;
                        container.appendChild(folderDiv);
                    } else {
                        stats.files++;
                        const fileDiv = document.createElement('div');
                        fileDiv.className = 'file';
                        
                        const fileInfoHtml = `
                            <div class="file-info">
                                ${node.size ? `<span class="file-size">${node.size}</span>` : ''}
                                ${node.last_modified ? `<span class="file-date">📅 ${node.last_modified}</span>` : ''}
                            </div>
                        `;
                        
                        fileDiv.innerHTML = `
                            <span class="icon">📄</span>
                            <span>${name}</span>
                            ${fileInfoHtml}
                        `;
                        fileDiv.onclick = () => window.open(node.url, '_blank');
                        container.appendChild(fileDiv);
                    }
                }
                
                if (node.type === 'folder') {
                    searchTree(node, query, container);
                }
            });
        }
        
        // Event listeners
        document.getElementById('searchInput').addEventListener('input', (e) => {
            search(e.target.value);
        });
        
        document.getElementById('expandAll').addEventListener('click', expandAll);
        document.getElementById('collapseAll').addEventListener('click', collapseAll);
        document.getElementById('homeBtn').addEventListener('click', (e) => {
            e.preventDefault();
            stats = { folders: 0, files: 0 };
            renderTree(treeData);
            updateStats();
            document.getElementById('searchInput').value = '';
        });
        
        // Load data on page load
        loadData();
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
    parser.add_argument('--url', help='Base URL to crawl (overrides config)')
    parser.add_argument('--json', help='JSON output/input file (overrides config)')
    parser.add_argument('--html', help='HTML output file (overrides config)')
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