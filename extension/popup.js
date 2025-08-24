function switchTab(tabId) {
  // Update tab buttons
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');

  // Update tab panes
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });
  document.getElementById(`${tabId}Tab`).classList.add('active');
}

let overrideActor = '';
let overrideResolution = ''; // Default resolution
let overrideContentType = 'song'; // Default content type
document.getElementById('sendButton').addEventListener('click', async () => {
  const statusDiv = document.getElementById('status');
  const extractedDataDiv = document.getElementById('extractedData');
  const mqttStatusBox = document.getElementById('mqttStatus');
  const finalJsonBox = document.getElementById('finalJsonBox');

  overrideActor = document.getElementById('actorInput').value;
  overrideResolution = document.getElementById('resolutionSelect').value; // <-- Add this line

  console.log("🎭 [POPUP] Using override actor:", overrideActor);
  // Switch to extracted data tab
  switchTab('extracted');

  // Helper function to add timestamped messages to MQTT status box
  const addMqttStatus = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString();
    let prefix;
    if (type === 'error') {
      prefix = '❌ ERROR:';
    } else if (type === 'success') {
      prefix = '✅ SUCCESS:';
    } else {
      prefix = 'ℹ️ INFO:';
    }
    const statusMessage = `[${timestamp}] ${prefix} ${message}\n`;
    mqttStatusBox.value += statusMessage;
    mqttStatusBox.scrollTop = mqttStatusBox.scrollHeight; // Auto-scroll to bottom
  };
  
  // Clear previous status and final JSON
  mqttStatusBox.value = '';
  finalJsonBox.value = '';
  addMqttStatus('Starting video data extraction...');
  
  statusDiv.textContent = 'Getting video data...';
  extractedDataDiv.classList.remove('show');

  // Get the active tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // Check if the current tab is a YouTube video page
  if (!tab?.url?.includes("youtube.com/watch")) {
    statusDiv.textContent = 'Please navigate to a YouTube video page.';
    addMqttStatus('Failed: Not on a YouTube video page', 'error');
    return;
  }

  addMqttStatus('Executing content script on YouTube page...');

  // Execute content script to get data from the page
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ['content.js']
  }, () => {
    // Send a message to the content script to trigger data extraction
    chrome.tabs.sendMessage(tab.id, { action: "getData" }, (response) => {
      if (chrome.runtime.lastError) {
        console.error(chrome.runtime.lastError);
        const errorMsg = 'Content script error: ' + chrome.runtime.lastError.message;
        statusDiv.textContent = 'Error: ' + chrome.runtime.lastError.message;
        addMqttStatus(errorMsg, 'error');
        return;
      }
      if (response && response.status === "success") {
        // Display the extracted data
        const formattedData = JSON.stringify(response.data, null, 2);
        extractedDataDiv.textContent = formattedData;
        extractedDataDiv.classList.add('show');
        
        statusDiv.textContent = 'Data retrieved successfully. Processing with Ollama AI to create structured JSON...';
        addMqttStatus('Video data extracted successfully');
        addMqttStatus(`Content Type: ${response.data.contentType}, Title: "${response.data.title}"`);
        addMqttStatus('🤖 Processing with Ollama AI to extract structured JSON (LNG, ACT, MP4URL, RES)...');
        
        // Send the data to the background script for Ollama processing and MQTT sending
        addMqttStatus('🤖 Sending data to Ollama AI for structured JSON processing...');
        console.log("🤖 [POPUP] Sending video data to background for Ollama processing:", response.data);

        // Get user config from input boxes
        const mqttHostPort = document.getElementById('mqttHostPort').value.trim();
        const ollamaHostPort = document.getElementById('ollamaHostPort').value.trim();
        const mTopic = document.getElementById('mTopic').value.trim();
        const ollamaModel = document.getElementById('ollamaModel').value.trim();

        // Helper to split host:port
        function splitHostPort(str, defaultPort) {
          const [host, port] = str.split(':');
          return { host, port: port ? parseInt(port, 10) : defaultPort };
        }
        const mqttConfig = splitHostPort(mqttHostPort, 9001);
        const ollamaConfig = splitHostPort(ollamaHostPort, 12345);


        // Add the model info to the message
        chrome.runtime.sendMessage({
          action: "sendMqttMessage",
          data: {
            extract: {...response.data, overrideActor, overrideResolution, overrideContentType},
            config: {
              mTopic: mTopic,
              mqttHost: mqttConfig.host,
              mqttPort: mqttConfig.port,
              ollamaHost: ollamaConfig.host,
              ollamaPort: ollamaConfig.port,
              ollamaModel: ollamaModel
            }
          }
        }, (res) => {
          console.log("📡 [POPUP] Background script response:", res);
          if (res && res.status === "success") {
            // Switch to final JSON tab when showing the result
            switchTab('final');
            
            statusDiv.textContent = 'Structured JSON sent via MQTT!';
            addMqttStatus('✅ Structured JSON (LNG, ACT, MP4URL, RES) sent successfully via MQTT', 'success');
            console.log("✅ [POPUP] Complete pipeline successful: YouTube → Ollama → MQTT");
            
            // Display the final JSON message that was sent
            if (res?.details?.finalJsonPayload) {
              const finalJson = JSON.stringify(res.details.finalJsonPayload, null, 2);
              finalJsonBox.value = finalJson;
              addMqttStatus('📊 Final JSON payload displayed in textbox', 'success');
              console.log("📊 [POPUP] Final JSON payload:", finalJson);
            } else {
              addMqttStatus('⚠️ Final JSON payload not available in response', 'error');
              finalJsonBox.value = 'Final JSON payload not available in response';
            }
            
            // Display detailed success information
            if (res?.details) {
              addMqttStatus(`Broker: ${res.details.broker}`);
              addMqttStatus(`Topic: ${res.details.topic}`);
              addMqttStatus(`Payload size: ${res.details.payloadSize} bytes`);
              addMqttStatus(`QoS: ${res.details.qos}`);
              addMqttStatus(`Sent at: ${new Date(res.details.timestamp).toLocaleString()}`);
              addMqttStatus('✨ Structured JSON sent: {LNG, ACT, MP4URL, RES}', 'success');
            }
            // After displaying all success messages, switch back to status tab
            setTimeout(() => {
              switchTab('status');
            }, 5000);
          } else {
            // On error, stay on status tab
            switchTab('status');
            console.error("❌ [POPUP] Background script error:", res);
            const errorMsg = res ? res.message : 'Unknown error occurred';
            statusDiv.textContent = `Error: ${errorMsg}`;
            addMqttStatus(`🤖 Ollama/MQTT pipeline failed: ${errorMsg}`, 'error');
            
            // Display detailed error information
            if (res?.errorCode) {
              addMqttStatus(`Error Code: ${res.errorCode}`, 'error');
            }
            if (res?.details) {
              addMqttStatus(`Details: ${res.details}`, 'error');
            }
            
            // Add troubleshooting hints based on error type
            if (errorMsg.includes('WebSocket') || res?.errorCode === 4) {
              addMqttStatus('💡 TIP: Ensure your MQTT broker supports WebSocket connections', 'error');
              addMqttStatus('💡 TIP: Try using WebSocket port (8083, 8084) instead of standard MQTT port (1883)', 'error');
            } else if (errorMsg.includes('timeout') || res?.errorCode === 8) {
              addMqttStatus('💡 TIP: Check if the broker IP address and port are correct', 'error');
              addMqttStatus('💡 TIP: Verify the MQTT broker is running and accessible', 'error');
            } else if (res?.errorCode === 7) {
              addMqttStatus('💡 TIP: Network connectivity issue - check firewall/network settings', 'error');
            }
          }
        });
      } else {
        const errorMsg = response ? response.message : 'Unknown error occurred';
        statusDiv.textContent = `Error: ${errorMsg}`;
        addMqttStatus(`Data extraction failed: ${errorMsg}`, 'error');
        extractedDataDiv.classList.remove('show');
      }
    });
  });
});

// Add event listener for clear status button
document.getElementById('clearStatusButton').addEventListener('click', () => {
  const mqttStatusBox = document.getElementById('mqttStatus');
  mqttStatusBox.value = '';
  switchTab('status');
  // Add a cleared message with timestamp
  const timestamp = new Date().toLocaleTimeString();
  mqttStatusBox.value = `[${timestamp}] 🗑️ CLEARED: Status log cleared by user\n`;
});

// Initialize status box with configuration info
document.addEventListener('DOMContentLoaded', () => {
  const resolutionSelect = document.getElementById('resolutionSelect');
  const mqttStatusBox = document.getElementById('mqttStatus');
  const finalJsonBox = document.getElementById('finalJsonBox');
  const timestamp = new Date().toLocaleTimeString();
  
  // Initialize tabs
  document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', () => {
      switchTab(button.dataset.tab);
    });
  });

  // Focus status tab by default
  switchTab('status');
  // Initialize status box
  mqttStatusBox.value = `[${timestamp}] ℹ️ INFO: Extension loaded - Ready to extract structured JSON {LNG, ACT, MP4URL, RES}\n`;
  
  // Initialize final JSON box with placeholder text
  finalJsonBox.placeholder = "{\n  \"LNG\": \"English\",\n  \"ACT\": \"Actor Name\",\n  \"MP4URL\": \"video_url\",\n  \"RES\": 1080\n}";
  
  // Fetch broker and Ollama configuration from background script
  chrome.runtime.sendMessage({ action: "getBrokerInfo" }, (response) => {
    if (response?.status === "success") {
      const brokerInfo = response.brokerInfo;
      const ollamaInfo = response.ollamaInfo;
      
      // Update model input with current value if it exists
      if (ollamaInfo?.model) {
        document.getElementById('ollamaModel').value = ollamaInfo.model;
      }

      mqttStatusBox.value += `[${timestamp}] ℹ️ INFO: MQTT Broker: ${brokerInfo.host}:${brokerInfo.port}\n`;
      mqttStatusBox.value += `[${timestamp}] ℹ️ INFO: MQTT Topic: "${brokerInfo.topic}"\n`;
      mqttStatusBox.value += `[${timestamp}] 🤖 INFO: AI Model: ${ollamaInfo.model} at ${ollamaInfo.host}\n`;
      mqttStatusBox.value += `[${timestamp}] ⚠️  NOTE: ${brokerInfo.note}\n`;
      mqttStatusBox.value += `[${timestamp}] ✨ NOTE: ${ollamaInfo.note}\n`;
      mqttStatusBox.value += `[${timestamp}] 📊 OUTPUT: Structured JSON format {LNG, ACT, MP4URL, RES}\n`;
      mqttStatusBox.value += `[${timestamp}] ℹ️ INFO: Click "Get & Send" on a YouTube video page to start\n`;
    } else {
      mqttStatusBox.value += `[${timestamp}] 📊 OUTPUT: Structured JSON format {LNG, ACT, MP4URL, RES}\n`;
      mqttStatusBox.value += `[${timestamp}] ℹ️ INFO: Click "Get & Send" on a YouTube video page to start\n`;
    }
  });
});