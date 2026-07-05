/**
 * app.js: JS code for the EMA- Elderly Medical Assistant demo app.
 */

/**
 * WebSocket handling
 */
const userId = "demo-user";
const sessionId = "demo-session-" + Math.random().toString(36).substring(7);
let websocket = null;
let is_audio = false;
let ttsEnabled = localStorage.getItem('ttsEnabled') !== 'false';

// WebSocket URL helper
function getWebSocketUrl() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return wsProtocol + "//" + window.location.host + "/ws/" + userId + "/" + sessionId;
}

// Get DOM elements
const messageForm = document.getElementById("messageForm");
const messageInput = document.getElementById("message");
const messagesDiv = document.getElementById("messages");
const statusIndicator = document.getElementById("statusIndicator");
const statusText = document.getElementById("statusText");
const consoleContent = document.getElementById("consoleContent");
const clearConsoleBtn = document.getElementById("clearConsole");
const showAudioEventsCheckbox = document.getElementById("showAudioEvents");
let currentMessageId = null;
let currentBubbleElement = null;
let currentBubbleText = '';
let currentBubbleAuthor = null;
let currentInputTranscriptionId = null;
let currentInputTranscriptionElement = null;
let currentInputTranscriptionText = ''; // In-memory accumulation for voice input
let currentOutputTranscriptionId = null;
let currentOutputTranscriptionElement = null;
let currentOutputTranscriptionText = '';
let inputTranscriptionFinished = false;
let hasOutputTranscriptionInTurn = false;

function cleanCJKSpaces(text) {
  const cjkPattern = /[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf\uff00-\uffef]/;

  return text.replace(/(\S)\s+(?=\S)/g, (match, char1) => {
  
    const nextCharMatch = text.match(new RegExp(char1 + '\\s+(.)', 'g'));
    if (nextCharMatch && nextCharMatch.length > 0) {
      const char2 = nextCharMatch[0].slice(-1);
      
      if (cjkPattern.test(char1) && cjkPattern.test(char2)) {
        return char1;
      }
    }
    return match;
  });
}

// Console logging functionality
function formatTimestamp() {
  const now = new Date();
  return now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
}

let patientConsoleEntries = [];
let gridConsoleEntries = [];
let activeConsoleTab = 'patient';

function addConsoleEntry(type, content, data = null, emoji = null, author = null, isAudio = false, isGrid = false) {
  const newEntry = {
    type,
    content,
    data,
    emoji,
    author,
    isAudio,
    isGrid,
    timestamp: formatTimestamp()
  };

  if (isGrid) {
    gridConsoleEntries.push(newEntry);
  } else {
    patientConsoleEntries.push(newEntry);
  }

  if ((isGrid && activeConsoleTab === 'grid') || (!isGrid && activeConsoleTab === 'patient')) {
    renderConsole();
  }
}

function renderConsole() {
  consoleContent.innerHTML = '';
  const entries = activeConsoleTab === 'patient' ? patientConsoleEntries : gridConsoleEntries;

  entries.forEach(entry => {
    if (entry.isAudio && !showAudioEventsCheckbox.checked) {
      return;
    }

    const entryEl = document.createElement("div");
    entryEl.className = `console-entry ${entry.type}`;

    const header = document.createElement("div");
    header.className = "console-entry-header";

    const leftSection = document.createElement("div");
    leftSection.className = "console-entry-left";

    if (entry.emoji) {
      const emojiIcon = document.createElement("span");
      emojiIcon.className = "console-entry-emoji";
      emojiIcon.textContent = entry.emoji;
      leftSection.appendChild(emojiIcon);
    }

    const expandIcon = document.createElement("span");
    expandIcon.className = "console-expand-icon";
    expandIcon.textContent = entry.data ? "▶" : "";

    const typeLabel = document.createElement("span");
    typeLabel.className = "console-entry-type";
    typeLabel.textContent = entry.type === 'outgoing' ? '↑ Upstream' : entry.type === 'incoming' ? '↓ Downstream' : '⚠ Error';

    leftSection.appendChild(expandIcon);
    leftSection.appendChild(typeLabel);

    if (entry.author) {
      const authorBadge = document.createElement("span");
      authorBadge.className = "console-entry-author";
      authorBadge.textContent = entry.author;
      authorBadge.setAttribute('data-author', entry.author);
      leftSection.appendChild(authorBadge);
    }

    const timestamp = document.createElement("span");
    timestamp.className = "console-entry-timestamp";
    timestamp.textContent = entry.timestamp;

    header.appendChild(leftSection);
    header.appendChild(timestamp);

    const contentDiv = document.createElement("div");
    contentDiv.className = "console-entry-content";
    contentDiv.textContent = entry.content;

    entryEl.appendChild(header);
    entryEl.appendChild(contentDiv);

    if (entry.data) {
      const jsonDiv = document.createElement("div");
      jsonDiv.className = "console-entry-json collapsed";
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(entry.data, null, 2);
      jsonDiv.appendChild(pre);
      entryEl.appendChild(jsonDiv);

      entryEl.classList.add("expandable");

      entryEl.addEventListener("click", () => {
        const isExpanded = !jsonDiv.classList.contains("collapsed");
        if (isExpanded) {
          jsonDiv.classList.add("collapsed");
          expandIcon.textContent = "▶";
          entryEl.classList.remove("expanded");
        } else {
          jsonDiv.classList.remove("collapsed");
          expandIcon.textContent = "▼";
          entryEl.classList.add("expanded");
        }
      });
    }

    consoleContent.appendChild(entryEl);
  });

  consoleContent.scrollTop = consoleContent.scrollHeight;
}

function clearConsole() {
  if (activeConsoleTab === 'patient') {
    patientConsoleEntries = [];
  } else {
    gridConsoleEntries = [];
  }
  renderConsole();
}

// Clear console button handler
clearConsoleBtn.addEventListener('click', clearConsole);

// Show audio checkbox changes should re-render
showAudioEventsCheckbox.addEventListener('change', renderConsole);

// Tabs click handlers
const patientConsoleTab = document.getElementById("patientConsoleTab");
const gridConsoleTab = document.getElementById("gridConsoleTab");

if (patientConsoleTab && gridConsoleTab) {
  patientConsoleTab.addEventListener("click", () => {
    activeConsoleTab = 'patient';
    patientConsoleTab.classList.add("active");
    gridConsoleTab.classList.remove("active");
    renderConsole();
  });

  gridConsoleTab.addEventListener("click", () => {
    activeConsoleTab = 'grid';
    gridConsoleTab.classList.add("active");
    patientConsoleTab.classList.remove("active");
    renderConsole();
  });
}

// Update connection status UI
function updateConnectionStatus(connected) {
  if (connected) {
    statusIndicator.classList.remove("disconnected");
    statusText.textContent = "Connected";
  } else {
    statusIndicator.classList.add("disconnected");
    statusText.textContent = "Disconnected";
  }
}

// Create a message bubble element
function createMessageBubble(text, isUser, isPartial = false) {
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${isUser ? "user" : "agent"}`;

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "bubble";

  if (!isUser && typeof marked !== 'undefined') {
    // Render markdown for agent responses
    const proseDiv = document.createElement("div");
    proseDiv.className = "bubble-prose";
    proseDiv.innerHTML = marked.parse(text || '');
    if (isPartial) {
      const typingSpan = document.createElement("span");
      typingSpan.className = "typing-indicator";
      proseDiv.appendChild(typingSpan);
    }
    bubbleDiv.appendChild(proseDiv);
  } else {
    const textP = document.createElement("p");
    textP.className = "bubble-text";
    textP.textContent = text;
    if (isPartial && !isUser) {
      const typingSpan = document.createElement("span");
      typingSpan.className = "typing-indicator";
      textP.appendChild(typingSpan);
    }
    bubbleDiv.appendChild(textP);
  }

  messageDiv.appendChild(bubbleDiv);
  return messageDiv;
}

// Create an image message bubble element
function createImageBubble(imageDataUrl, isUser) {
  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${isUser ? "user" : "agent"}`;

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "bubble image-bubble";

  const img = document.createElement("img");
  img.src = imageDataUrl;
  img.className = "bubble-image";
  img.alt = "Captured image";

  bubbleDiv.appendChild(img);
  messageDiv.appendChild(bubbleDiv);

  return messageDiv;
}

// Update existing message bubble text
function updateMessageBubble(element, text, isPartial = false) {
  const isAgent = element.classList.contains('agent');

  if (isAgent && typeof marked !== 'undefined') {
    let proseDiv = element.querySelector('.bubble-prose');
    if (!proseDiv) {
  
      const oldText = element.querySelector('.bubble-text');
      if (oldText) oldText.remove();
      proseDiv = document.createElement('div');
      proseDiv.className = 'bubble-prose';
      element.querySelector('.bubble').appendChild(proseDiv);
    }
   
    const existingIndicator = proseDiv.querySelector('.typing-indicator');
    if (existingIndicator) existingIndicator.remove();
    proseDiv.innerHTML = marked.parse(text || '');
    if (isPartial) {
      const typingSpan = document.createElement('span');
      typingSpan.className = 'typing-indicator';
      proseDiv.appendChild(typingSpan);
    }
  } else {
    const textElement = element.querySelector('.bubble-text');
    if (!textElement) return;
    const existingIndicator = textElement.querySelector('.typing-indicator');
    if (existingIndicator) existingIndicator.remove();
    textElement.textContent = text;
    if (isPartial) {
      const typingSpan = document.createElement('span');
      typingSpan.className = 'typing-indicator';
      textElement.appendChild(typingSpan);
    }
  }
}

// Add a system message
function addSystemMessage(text) {
  const messageDiv = document.createElement("div");
  messageDiv.className = "system-message";
  messageDiv.textContent = text;
  messagesDiv.appendChild(messageDiv);
  scrollToBottom();
}

// Scroll to bottom of messages
function scrollToBottom() {
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function sanitizeEventForDisplay(event) {
  const sanitized = JSON.parse(JSON.stringify(event));

  if (sanitized.content && sanitized.content.parts) {
    sanitized.content.parts = sanitized.content.parts.map(part => {
      if (part.inlineData && part.inlineData.data) {

        const byteSize = Math.floor(part.inlineData.data.length * 0.75);
        return {
          ...part,
          inlineData: {
            ...part.inlineData,
            data: `(${byteSize.toLocaleString()} bytes)`
          }
        };
      }
      return part;
    });
  }

  return sanitized;
}

// WebSocket handlers
function connectWebsocket() {
  // Connect websocket
  const ws_url = getWebSocketUrl();
  websocket = new WebSocket(ws_url);

  // Handle connection open
  websocket.onopen = function () {
    console.log("WebSocket connection opened.");
    updateConnectionStatus(true);
    addSystemMessage("Connected to EMA server");

    // Log to console
    addConsoleEntry('incoming', 'WebSocket Connected', {
      userId: userId,
      sessionId: sessionId,
      url: ws_url
    }, '🔌', 'system');

    // Enable the Send button
    document.getElementById("sendButton").disabled = false;
    addSubmitHandler();

    // Sync TTS preference with backend
    syncTtsPreference();

    // Automatically trigger the session for the default user (Ahmad)
    sendMessage("__START_SESSION__");
  };

  // Handle incoming messages
  websocket.onmessage = function (event) {
    // Parse the incoming ADK Event
    const adkEvent = JSON.parse(event.data);
    console.log("[AGENT TO CLIENT] ", adkEvent);

    // Log to console panel
    let eventSummary = 'Event';
    let eventEmoji = '📨'; // Default emoji
    const author = adkEvent.author || 'system';

    if (adkEvent.turnComplete) {
      eventSummary = 'Turn Complete';
      eventEmoji = '✅';
    } else if (adkEvent.interrupted) {
      eventSummary = 'Interrupted';
      eventEmoji = '⏸️';
    } else if (adkEvent.inputTranscription) {
      // Show transcription text in summary
      const transcriptionText = adkEvent.inputTranscription.text || '';
      const truncated = transcriptionText.length > 60
        ? transcriptionText.substring(0, 60) + '...'
        : transcriptionText;
      eventSummary = `Input Transcription: "${truncated}"`;
      eventEmoji = '📝';
    } else if (adkEvent.outputTranscription) {
      // Show transcription text in summary
      const transcriptionText = adkEvent.outputTranscription.text || '';
      const truncated = transcriptionText.length > 60
        ? transcriptionText.substring(0, 60) + '...'
        : transcriptionText;
      eventSummary = `Output Transcription: "${truncated}"`;
      eventEmoji = '📝';
    } else if (adkEvent.usageMetadata) {
      // Show token usage information
      const usage = adkEvent.usageMetadata;
      const promptTokens = usage.promptTokenCount || 0;
      const responseTokens = usage.candidatesTokenCount || 0;
      const totalTokens = usage.totalTokenCount || 0;
      eventSummary = `Token Usage: ${totalTokens.toLocaleString()} total (${promptTokens.toLocaleString()} prompt + ${responseTokens.toLocaleString()} response)`;
      eventEmoji = '📊';
    } else if (adkEvent.content && adkEvent.content.parts) {
      const hasText = adkEvent.content.parts.some(p => p.text);
      const hasAudio = adkEvent.content.parts.some(p => p.inlineData);
      const hasExecutableCode = adkEvent.content.parts.some(p => p.executableCode);
      const hasCodeExecutionResult = adkEvent.content.parts.some(p => p.codeExecutionResult);

      if (hasExecutableCode) {
        // Show executable code
        const codePart = adkEvent.content.parts.find(p => p.executableCode);
        if (codePart && codePart.executableCode) {
          const code = codePart.executableCode.code || '';
          const language = codePart.executableCode.language || 'unknown';
          const truncated = code.length > 60
            ? code.substring(0, 60).replace(/\n/g, ' ') + '...'
            : code.replace(/\n/g, ' ');
          eventSummary = `Executable Code (${language}): ${truncated}`;
          eventEmoji = '💻';
        }
      }

      if (hasCodeExecutionResult) {
        // Show code execution result
        const resultPart = adkEvent.content.parts.find(p => p.codeExecutionResult);
        if (resultPart && resultPart.codeExecutionResult) {
          const outcome = resultPart.codeExecutionResult.outcome || 'UNKNOWN';
          const output = resultPart.codeExecutionResult.output || '';
          const truncatedOutput = output.length > 60
            ? output.substring(0, 60).replace(/\n/g, ' ') + '...'
            : output.replace(/\n/g, ' ');
          eventSummary = `Code Execution Result (${outcome}): ${truncatedOutput}`;
          eventEmoji = outcome === 'OUTCOME_OK' ? '✅' : '❌';
        }
      }

      if (hasText) {
        // Show text preview in summary
        const textPart = adkEvent.content.parts.find(p => p.text);
        if (textPart && textPart.text) {
          const text = textPart.text;
          const truncated = text.length > 80
            ? text.substring(0, 80) + '...'
            : text;
          eventSummary = `Text: "${truncated}"`;
          eventEmoji = '💭';
        } else {
          eventSummary = 'Text Response';
          eventEmoji = '💭';
        }
      }

      if (hasAudio) {
        // Extract audio info for summary
        const audioPart = adkEvent.content.parts.find(p => p.inlineData);
        if (audioPart && audioPart.inlineData) {
          const mimeType = audioPart.inlineData.mimeType || 'unknown';
          const dataLength = audioPart.inlineData.data ? audioPart.inlineData.data.length : 0;
          // Base64 string length / 4 * 3 gives approximate bytes
          const byteSize = Math.floor(dataLength * 0.75);
          eventSummary = `Audio Response: ${mimeType} (${byteSize.toLocaleString()} bytes)`;
          eventEmoji = '🔊';
        } else {
          eventSummary = 'Audio Response';
          eventEmoji = '🔊';
        }

        // Log audio event with isAudio flag (filtered by checkbox)
        const sanitizedEvent = sanitizeEventForDisplay(adkEvent);
        addConsoleEntry('incoming', eventSummary, sanitizedEvent, eventEmoji, author, true);
      }
    }

    // Create a sanitized version for console display (replace large audio data with summary)
    // Skip if already logged as audio event above
    const isAudioOnlyEvent = adkEvent.content && adkEvent.content.parts &&
      adkEvent.content.parts.some(p => p.inlineData) &&
      !adkEvent.content.parts.some(p => p.text);
    if (!isAudioOnlyEvent) {
      const sanitizedEvent = sanitizeEventForDisplay(adkEvent);
      addConsoleEntry('incoming', eventSummary, sanitizedEvent, eventEmoji, author);
    }

    // Handle turn complete event
    if (adkEvent.turnComplete === true) {
      // Safely finalize the current bubble (remove typing indicator)
      if (currentBubbleElement) {
        const indicator = currentBubbleElement.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
      }
      if (currentOutputTranscriptionElement) {
        const indicator = currentOutputTranscriptionElement.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
      }

      currentMessageId = null;
      currentBubbleElement = null;
      currentBubbleText = '';
      currentBubbleAuthor = null;
      currentInputTranscriptionId = null;
      currentInputTranscriptionElement = null;
      currentInputTranscriptionText = '';
      currentOutputTranscriptionId = null;
      currentOutputTranscriptionElement = null;
      currentOutputTranscriptionText = '';
      inputTranscriptionFinished = false;
      hasOutputTranscriptionInTurn = false;

      // Remove thinking indicator when turn is fully complete
      removeThinkingIndicator();

      // Remove speaker animation from all agent bubbles
      document.querySelectorAll('.ema-speaking').forEach(el => {
        el.classList.remove('ema-speaking');
        const icon = el.querySelector('.speaker-icon');
        if (icon) icon.remove();
      });
      return;
    }

    // Handle interrupted event
    if (adkEvent.interrupted === true) {
      if (audioPlayerNode) {
        audioPlayerNode.port.postMessage({ command: "endOfAudio" });
      }

      // Mark partial bubbles as interrupted (safe — no .bubble-text needed)
      if (currentBubbleElement) {
        const indicator = currentBubbleElement.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
        currentBubbleElement.classList.add('interrupted');
      }
      if (currentOutputTranscriptionElement) {
        const indicator = currentOutputTranscriptionElement.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
        currentOutputTranscriptionElement.classList.add('interrupted');
      }

      currentMessageId = null;
      currentBubbleElement = null;
      currentBubbleText = '';
      currentBubbleAuthor = null;
      currentInputTranscriptionId = null;
      currentInputTranscriptionElement = null;
      currentInputTranscriptionText = '';
      currentOutputTranscriptionId = null;
      currentOutputTranscriptionElement = null;
      currentOutputTranscriptionText = '';
      inputTranscriptionFinished = false;
      hasOutputTranscriptionInTurn = false;
      return;
    }

    // Handle input transcription (user's spoken words)
    if (adkEvent.inputTranscription && adkEvent.inputTranscription.text) {
      const transcriptionText = adkEvent.inputTranscription.text;
      const isFinished = adkEvent.inputTranscription.finished;

      if (transcriptionText) {
        if (inputTranscriptionFinished) return;

        // Determine display text — show "Transcribing..." for placeholder
        const isPlaceholder = transcriptionText === '_TRANSCRIBING_';
        const displayText = isPlaceholder
          ? 'Transcribing...'
          : cleanCJKSpaces(transcriptionText);

        if (currentInputTranscriptionId == null) {
          currentInputTranscriptionId = Math.random().toString(36).substring(7);
          currentInputTranscriptionText = isPlaceholder ? '' : transcriptionText;
          currentInputTranscriptionElement = createMessageBubble(
            displayText, true, !isFinished
          );
          currentInputTranscriptionElement.id = currentInputTranscriptionId;
          currentInputTranscriptionElement.classList.add('transcription');
          messagesDiv.appendChild(currentInputTranscriptionElement);
        } else {
          if (currentOutputTranscriptionId == null && currentMessageId == null) {
            if (isFinished) {
              currentInputTranscriptionText = transcriptionText;
              updateMessageBubble(
                currentInputTranscriptionElement,
                displayText,
                false
              );
            } else if (!isPlaceholder) {
              currentInputTranscriptionText += transcriptionText;
              updateMessageBubble(
                currentInputTranscriptionElement,
                cleanCJKSpaces(currentInputTranscriptionText),
                true
              );
            }
          }
        }

        if (isFinished) {
          currentInputTranscriptionId = null;
          currentInputTranscriptionElement = null;
          currentInputTranscriptionText = '';
          inputTranscriptionFinished = true;
          showThinkingIndicator();
        }

        scrollToBottom();
      }
    }

    // Handle output transcription (model's spoken words)
    if (adkEvent.outputTranscription && adkEvent.outputTranscription.text) {
      const transcriptionText = adkEvent.outputTranscription.text;
      const isFinished = adkEvent.outputTranscription.finished;
      hasOutputTranscriptionInTurn = true;

      // Keep thinking indicator alive — only dismiss on turnComplete

      if (transcriptionText) {
        // Safely finalize any active input transcription
        if (currentInputTranscriptionId != null && currentOutputTranscriptionId == null) {
          const indicator = currentInputTranscriptionElement
            ? currentInputTranscriptionElement.querySelector('.typing-indicator')
            : null;
          if (indicator) indicator.remove();
          currentInputTranscriptionId = null;
          currentInputTranscriptionElement = null;
          currentInputTranscriptionText = '';
          inputTranscriptionFinished = true;
        }

        if (currentOutputTranscriptionId == null) {
          // Create new transcription bubble for agent
          currentOutputTranscriptionId = Math.random().toString(36).substring(7);
          currentOutputTranscriptionText = transcriptionText;
          currentOutputTranscriptionElement = createMessageBubble(transcriptionText, false, !isFinished);
          currentOutputTranscriptionElement.id = currentOutputTranscriptionId;
          currentOutputTranscriptionElement.classList.add("transcription");
          messagesDiv.appendChild(currentOutputTranscriptionElement);
        } else {
          if (isFinished) {
            currentOutputTranscriptionText = transcriptionText;
            updateMessageBubble(currentOutputTranscriptionElement, transcriptionText, false);
          } else {
            currentOutputTranscriptionText += transcriptionText;
            updateMessageBubble(currentOutputTranscriptionElement, currentOutputTranscriptionText, true);
          }
        }

        // If transcription is finished, reset the state
        if (isFinished) {
          currentOutputTranscriptionId = null;
          currentOutputTranscriptionElement = null;
        }

        scrollToBottom();
      }
    }

    // Handle content events (text or audio)
    if (adkEvent.content && adkEvent.content.parts) {
      const parts = adkEvent.content.parts;

      // Keep thinking indicator alive — only dismiss on turnComplete

      // Finalize any active input transcription when server starts responding with content
      if (currentInputTranscriptionId != null && currentMessageId == null && currentOutputTranscriptionId == null) {
        // Remove typing indicator from the input transcription bubble
        const inputBubble = currentInputTranscriptionElement;
        if (inputBubble) {
          const indicator = inputBubble.querySelector('.typing-indicator');
          if (indicator) indicator.remove();
        }
        currentInputTranscriptionId = null;
        currentInputTranscriptionElement = null;
        inputTranscriptionFinished = true;
      }

      for (const part of parts) {
        // Handle inline data (audio)
        if (part.inlineData) {
          const mimeType = part.inlineData.mimeType;
          const data = part.inlineData.data;

          if (mimeType && mimeType.startsWith("audio/pcm")) {
            if (!ttsEnabled) continue;

            const audioBuffer = base64ToArray(data);

            if (audioPlayerNode) {
              audioPlayerNode.port.postMessage(audioBuffer);
            } else {
              pendingAudioChunks.push(audioBuffer);
              console.log(`TTS chunk buffered (player not ready). Queue: ${pendingAudioChunks.length}`);
            }

            // Show speaker animation on the latest agent bubble
            if (currentBubbleElement && audioPlayerNode) {
              currentBubbleElement.classList.add('ema-speaking');
              let speakerIcon = currentBubbleElement.querySelector('.speaker-icon');
              if (!speakerIcon) {
                speakerIcon = document.createElement('span');
                speakerIcon.className = 'speaker-icon';
                speakerIcon.innerHTML = '<span class="speaker-bar"></span><span class="speaker-bar"></span><span class="speaker-bar"></span>';
                const bubble = currentBubbleElement.querySelector('.bubble');
                if (bubble) bubble.appendChild(speakerIcon);
              }
            }
          }
        }

        // Handle text
        if (part.text) {
        
          if (part.thought) {
            continue;
          }

          const eventAuthor = adkEvent.author || 'agent';

          if (currentBubbleElement && currentBubbleAuthor !== eventAuthor) {
            const prevIndicator = currentBubbleElement.querySelector('.typing-indicator');
            if (prevIndicator) prevIndicator.remove();
            currentMessageId = null;
            currentBubbleElement = null;
            currentBubbleText = '';
          }

          if (currentMessageId == null) {
            currentMessageId = Math.random().toString(36).substring(7);
            currentBubbleAuthor = eventAuthor;
            currentBubbleText = part.text;
            currentBubbleElement = createMessageBubble(currentBubbleText, false, true);
            currentBubbleElement.id = currentMessageId;
            messagesDiv.appendChild(currentBubbleElement);
          } else {
            currentBubbleText += part.text;
            updateMessageBubble(currentBubbleElement, currentBubbleText, true);
          }

          scrollToBottom();
        }
      }
    }
  };

  // Handle connection close
  websocket.onclose = async function () {
    console.log("WebSocket connection closed.");
    updateConnectionStatus(false);
    document.getElementById("sendButton").disabled = true;
    addSystemMessage("Connection closed. Reconnecting in 5 seconds...");

    // Log to console
    addConsoleEntry('error', 'WebSocket Disconnected', {
      status: 'Connection closed',
      reconnecting: true,
      reconnectDelay: '5 seconds'
    }, '🔌', 'system');

    // Stop any orphaned audio sessions before reconnecting
    // We use async/await here because websocket.onclose can be async
    await stopAudio();

    setTimeout(function () {
      console.log("Reconnecting...");

      // Log reconnection attempt to console
      addConsoleEntry('outgoing', 'Reconnecting to EMA server...', {
        userId: userId,
        sessionId: sessionId
      }, '🔄', 'system');

      connectWebsocket();
    }, 5000);
  };

  websocket.onerror = function (e) {
    console.log("WebSocket error: ", e);
    updateConnectionStatus(false);

    // Log to console
    addConsoleEntry('error', 'WebSocket Error', {
      error: e.type,
      message: 'Connection error occurred'
    }, '⚠️', 'system');
  };
}
connectWebsocket();

// Add submit handler to the form
function addSubmitHandler() {
  messageForm.onsubmit = function (e) {
    e.preventDefault();
    const message = messageInput.value.trim();
    if (message) {
      // Add user message bubble
      const userBubble = createMessageBubble(message, true, false);
      messagesDiv.appendChild(userBubble);
      scrollToBottom();

      // Clear input
      messageInput.value = "";

      // Send message to server
      sendMessage(message);
      console.log("[CLIENT TO AGENT] " + message);
    }
    return false;
  };
}

// Send a message to the server as JSON
function sendMessage(message) {
  if (websocket && websocket.readyState == WebSocket.OPEN) {
    if (currentBubbleElement) {
      const indicator = currentBubbleElement.querySelector('.typing-indicator');
      if (indicator) indicator.remove();
    }
    currentMessageId = null;
    currentBubbleElement = null;
    currentBubbleText = '';
    currentBubbleAuthor = null;
    currentInputTranscriptionId = null;
    currentInputTranscriptionElement = null;
    currentInputTranscriptionText = '';
    inputTranscriptionFinished = false;
    removeThinkingIndicator();
    const payload = {
      type: "text",
      text: message
    };

    let hasImage = false;

    // Include pending image if exists
    if (pendingImageData) {
      payload.image = pendingImageData;
      payload.mimeType = pendingImageMime;
      hasImage = true;

      // Add user image bubble
      const imageBubble = createImageBubble(imagePreview.src, true);
      messagesDiv.appendChild(imageBubble);

      // Clear pending image
      clearPendingImage();
    }

    const jsonMessage = JSON.stringify(payload);
    websocket.send(jsonMessage);

    // Log to console panel
    addConsoleEntry('outgoing', 'User Message: ' + message, null, '💬', 'user');

    // Show contextual thinking indicator
    if (message === "__START_SESSION__") {
      showThinkingIndicator("Waking up EMA");
    } else {
      showThinkingIndicator(
        hasImage ? "Analyzing your prescription..." : "EMA is thinking"
      );
    }
  }
}

function clearPendingImage() {
  pendingImageData = null;
  pendingImageMime = null;
  imagePreviewContainer.style.display = "none";
  imagePreview.src = "";
}

let thinkingIndicatorElement = null;
let thinkingCycleTimer = null;

// Message sequences shown while the agent is processing.
// The first entry is the contextual seed (image vs. text), the rest cycle.
const THINKING_MESSAGES_IMAGE = [
  "Analyzing your prescription",
  "Reading medication details",
  "Checking dosage information",
  "Cross-referencing drug database",
  "Almost there"
];
const THINKING_MESSAGES_TEXT = [
  "EMA is thinking",
  "Analyzing",
  "Consulting knowledge base",
  "Preparing your response",
  "Almost there"
];

function showThinkingIndicator(message = "EMA is thinking") {
  // Guard: only one indicator at a time
  if (thinkingIndicatorElement) return;

  const isImage = message.toLowerCase().includes("analyz");
  const messages = isImage ? THINKING_MESSAGES_IMAGE : THINKING_MESSAGES_TEXT;

  thinkingIndicatorElement = document.createElement("div");
  thinkingIndicatorElement.className = "message agent thinking";

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "bubble";

  const contentWrapper = document.createElement("div");
  contentWrapper.style.display = "flex";
  contentWrapper.style.alignItems = "center";
  contentWrapper.style.gap = "0.75rem";

  const textSpan = document.createElement("span");
  textSpan.className = "thinking-label";
  textSpan.textContent = messages[0];

  const dotsDiv = document.createElement("div");
  dotsDiv.className = "thinking-dots";

  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("span");
    dot.className = "thinking-dot";
    dotsDiv.appendChild(dot);
  }

  contentWrapper.appendChild(textSpan);
  contentWrapper.appendChild(dotsDiv);
  bubbleDiv.appendChild(contentWrapper);
  thinkingIndicatorElement.appendChild(bubbleDiv);

  messagesDiv.appendChild(thinkingIndicatorElement);
  scrollToBottom();

  // Cycle through status messages every 3 seconds
  let msgIndex = 1;
  thinkingCycleTimer = setInterval(() => {
    if (!thinkingIndicatorElement) {
      clearInterval(thinkingCycleTimer);
      thinkingCycleTimer = null;
      return;
    }
    const label = thinkingIndicatorElement.querySelector('.thinking-label');
    if (label) {
      // Fade out → update text → fade in
      label.style.transition = 'opacity 0.3s ease';
      label.style.opacity = '0';
      setTimeout(() => {
        if (label) {
          label.textContent = messages[msgIndex % messages.length];
          label.style.opacity = '1';
        }
      }, 320);
      msgIndex++;
    }
  }, 3000);
}

function removeThinkingIndicator() {
  if (thinkingCycleTimer) {
    clearInterval(thinkingCycleTimer);
    thinkingCycleTimer = null;
  }
  if (thinkingIndicatorElement) {
    thinkingIndicatorElement.remove();
    thinkingIndicatorElement = null;
  }
}

// Helper to set button loading state
function setButtonLoading(buttonId, isLoading) {
  const button = document.getElementById(buttonId);
  if (!button) return;

  if (isLoading) {
    button.classList.add("btn-loading");
    button.disabled = true;
  } else {
    button.classList.remove("btn-loading");
    button.disabled = false;
  }
}

// Decode Base64 data to Array
// Handles both standard base64 and base64url encoding
function base64ToArray(base64) {
  let standardBase64 = base64.replace(/-/g, '+').replace(/_/g, '/');

  // Add padding if needed
  while (standardBase64.length % 4) {
    standardBase64 += '=';
  }

  const binaryString = window.atob(standardBase64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Camera handling
 */

const addPhotoButton = document.getElementById("addPhotoButton");
const uploadPhotoButton = document.getElementById("uploadPhotoButton");
const imagePreviewContainer = document.getElementById("imagePreviewContainer");
const imagePreview = document.getElementById("imagePreview");
const removeImageBtn = document.getElementById("removeImage");
const cameraModal = document.getElementById("cameraModal");
const cameraPreview = document.getElementById("cameraPreview");
const closeCameraModal = document.getElementById("closeCameraModal");
const cancelCamera = document.getElementById("cancelCamera");
const captureImageBtn = document.getElementById("captureImage");
const imageUpload = document.getElementById("imageUpload");

let pendingImageData = null; // Store base64 data
let pendingImageMime = null; // Store mime type

let cameraStream = null;

// Open camera modal and start preview
async function openCameraPreview() {
  try {
    // Request access to the user's webcam
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 768 },
        height: { ideal: 768 },
        facingMode: 'user'
      }
    });

    // Set the stream to the video element
    cameraPreview.srcObject = cameraStream;

    // Show the modal
    cameraModal.classList.add('show');

  } catch (error) {
    console.error('Error accessing camera:', error);
    addSystemMessage(`Failed to access camera: ${error.message}`);

    // Log to console
    addConsoleEntry('error', 'Camera access failed', {
      error: error.message,
      name: error.name
    }, '⚠️', 'system');
  }
}

// Close camera modal and stop preview
function closeCameraPreview() {
  // Stop the camera stream
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }

  // Clear the video source
  cameraPreview.srcObject = null;

  // Hide the modal
  cameraModal.classList.remove('show');
}

// Capture image from the live preview
function captureImageFromPreview() {
  if (!cameraStream) {
    addSystemMessage('No camera stream available');
    return;
  }

  try {
    const canvas = document.createElement('canvas');
    canvas.width = cameraPreview.videoWidth;
    canvas.height = cameraPreview.videoHeight;
    const context = canvas.getContext('2d');
    context.drawImage(cameraPreview, 0, 0, canvas.width, canvas.height);

    const imageDataUrl = canvas.toDataURL('image/jpeg', 0.85);

    // Set as pending image instead of sending immediately
    pendingImageData = imageDataUrl.split(',')[1];
    pendingImageMime = "image/jpeg";

    imagePreview.src = imageDataUrl;
    imagePreviewContainer.style.display = "flex";

    // Log to console
    addConsoleEntry('outgoing', `Image captured and queued`, {
      type: 'image/jpeg',
      dimensions: `${canvas.width}x${canvas.height}`
    }, '📸', 'user');

    closeCameraPreview();
  } catch (error) {
    console.error('Error capturing image:', error);
    addSystemMessage(`Failed to capture image: ${error.message}`);
  }
}

// Send image to server
function sendImage(base64Image, mimeType = "image/jpeg") {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    const jsonMessage = JSON.stringify({
      type: "image",
      data: base64Image,
      mimeType: mimeType
    });
    websocket.send(jsonMessage);
    console.log("[CLIENT TO AGENT] Sent image");
  }
}

// Event listeners
uploadPhotoButton.addEventListener("click", () => {
  imageUpload.click();
});
addPhotoButton.addEventListener("click", openCameraPreview);
removeImageBtn.addEventListener("click", clearPendingImage);
closeCameraModal.addEventListener("click", closeCameraPreview);
cancelCamera.addEventListener("click", closeCameraPreview);
captureImageBtn.addEventListener("click", captureImageFromPreview);


imageUpload.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    const imageDataUrl = e.target.result;
    pendingImageData = imageDataUrl.split(',')[1];
    pendingImageMime = file.type || "image/jpeg";

    imagePreview.src = imageDataUrl;
    imagePreviewContainer.style.display = "flex";

    // Log to console
    addConsoleEntry('outgoing', `Image attached: ${file.name}`, {
      name: file.name,
      size: file.size,
      type: pendingImageMime
    }, '📁', 'user');
  };

  reader.readAsDataURL(file);
  event.target.value = '';
});

// Close modal when clicking outside of it
cameraModal.addEventListener("click", (event) => {
  if (event.target === cameraModal) {
    closeCameraPreview();
  }
});

/**
 * Audio handling
 */

let audioPlayerNode;
let audioPlayerContext;
let audioRecorderNode;
let audioRecorderContext;
let micStream;

import { startAudioPlayerWorklet } from "./audio-player.js";
import { startAudioRecorderWorklet } from "./audio-recorder.js";

let audioOutputInitialized = false;

// Buffer for TTS audio chunks that arrive before the AudioContext is ready.
// Browser autoplay policy blocks AudioContext creation without a user gesture,
// so __START_SESSION__ audio would be silently dropped without this queue.
const pendingAudioChunks = [];

function flushPendingAudio() {
  if (!audioPlayerNode || pendingAudioChunks.length === 0) return;
  console.log(`Flushing ${pendingAudioChunks.length} buffered TTS chunk(s).`);
  for (const chunk of pendingAudioChunks) {
    audioPlayerNode.port.postMessage(chunk);
  }
  pendingAudioChunks.length = 0;
}

async function ensureAudioPlayerReady() {
  if (audioOutputInitialized) return;
  audioOutputInitialized = true;

  try {
    const [playerNode, playerCtx] = await startAudioPlayerWorklet();
    audioPlayerNode = playerNode;
    audioPlayerContext = playerCtx;

    if (audioPlayerContext.state === "suspended") {
      await audioPlayerContext.resume();
    }
    console.log("Audio output auto-initialized. State:", audioPlayerContext.state);

    // Play any TTS audio that arrived before the player was ready
    flushPendingAudio();
  } catch (error) {
    console.warn("Auto-init of audio output failed:", error);
    audioOutputInitialized = false; // Allow retry
  }
}

// Trigger on very first user click/touch anywhere on the page
document.addEventListener("click", () => ensureAudioPlayerReady(), { once: true });
document.addEventListener("touchstart", () => ensureAudioPlayerReady(), { once: true });

// Start audio (mic + reuse existing player output)
async function startAudio() {
  try {
    // Reuse auto-initialized audio output, or create if missing
    if (!audioPlayerNode) {
      const [playerNode, playerCtx] = await startAudioPlayerWorklet();
      audioPlayerNode = playerNode;
      audioPlayerContext = playerCtx;
      audioOutputInitialized = true;
    }

    // Ensure audio context is running
    if (audioPlayerContext.state === "suspended") {
      await audioPlayerContext.resume();
    }

    // Start audio input (microphone)
    const [recorderNode, recorderCtx, stream] = await startAudioRecorderWorklet(audioRecorderHandler);
    audioRecorderNode = recorderNode;
    audioRecorderContext = recorderCtx;
    micStream = stream;

    // Ensure recorder context is running
    if (audioRecorderContext.state === "suspended") {
      await audioRecorderContext.resume();
    }

    console.log("Audio session started successfully. States: Output=%s, Input=%s",
      audioPlayerContext.state, audioRecorderContext.state);
    return true;
  } catch (error) {
    console.error("Failed to start audio session:", error);
    addSystemMessage("Error: Could not access microphone or audio output.");
    is_audio = false;
    startAudioButton.querySelector(".material-symbols-rounded").textContent = "mic";
    startAudioButton.classList.remove("audio-active");
    return false;
  }
}

// Stop audio input (mic) but keep audio output (TTS player) alive
async function stopAudio() {
  console.log("stopAudio() called. is_audio was:", is_audio);
  is_audio = false;

  if (micStream) {
    console.log("Stopping microphone tracks...");
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }

  // Only close the recorder context; keep the player context alive for TTS
  if (audioRecorderContext) {
    console.log("Closing audio recorder context (state: %s)...", audioRecorderContext.state);
    try {
      await audioRecorderContext.close();
      console.log("Audio recorder context closed.");
    } catch (e) {
      console.warn("Error closing recorder context:", e);
    }
    audioRecorderContext = null;
    audioRecorderNode = null;
  }
}

// Toggle audio on/off when the user clicks the button
const startAudioButton = document.getElementById("startAudioButton");
let isStartingAudio = false;

startAudioButton.addEventListener("click", async () => {
  if (isStartingAudio) {
    console.log("Audio toggle already in progress, ignoring click.");
    return;
  }

  isStartingAudio = true;
  startAudioButton.disabled = true;

  try {
    if (!is_audio) {
      // START AUDIO
      console.log("Attempting to start audio...");
      startAudioButton.querySelector(".material-symbols-rounded").textContent = "hourglass_top";

      // Reset flags
      inputTranscriptionFinished = false;
      hasOutputTranscriptionInTurn = false;

      const success = await startAudio();

      if (success) {
        is_audio = true;
        startAudioButton.querySelector(".material-symbols-rounded").textContent = "stop_circle";
        startAudioButton.classList.add("audio-active");
        addSystemMessage("Audio mode enabled - you can now speak to EMA");
        addConsoleEntry('outgoing', 'Audio Mode Enabled', {
          status: 'Audio worklets started',
          message: 'Microphone active'
        }, '🎤', 'system');
      } else {
        console.error("Failed to start audio (startAudio returned false)");
        is_audio = false;
        startAudioButton.querySelector(".material-symbols-rounded").textContent = "mic";
        startAudioButton.classList.remove("audio-active");
      }
    } else {
      // STOP AUDIO
      console.log("Attempting to stop audio...");
      startAudioButton.querySelector(".material-symbols-rounded").textContent = "hourglass_bottom";

      // Send audio_stop signal to trigger turn-based processing on server
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        // Safety reset: finalize any stale bubble state from a previous turn
        if (currentBubbleElement) {
          const indicator = currentBubbleElement.querySelector('.typing-indicator');
          if (indicator) indicator.remove();
        }
        currentMessageId = null;
        currentBubbleElement = null;
        currentBubbleText = '';
        currentBubbleAuthor = null;
        removeThinkingIndicator();

        websocket.send(JSON.stringify({ type: "audio_stop" }));
      }

      // Release resources
      await stopAudio();

      // Don't show thinking indicator here - it will be shown when
      // the server sends the final inputTranscription with finished=true

      // Use a consistent state update
      is_audio = false;
      startAudioButton.querySelector(".material-symbols-rounded").textContent = "mic";
      startAudioButton.classList.remove("audio-active");

      addSystemMessage("Audio mode disabled - transcribing your speech...");
      addConsoleEntry('outgoing', 'Audio Mode Disabled', {
        status: 'Microphone stopped',
        signal: 'audio_stop sent'
      }, '🔇', 'system');
    }
  } catch (error) {
    console.error("Error in audio toggle handler:", error);
    addSystemMessage(`Audio error: ${error.message}`);
    // Reset to safe state
    is_audio = false;
    startAudioButton.querySelector(".material-symbols-rounded").textContent = "mic";
    startAudioButton.classList.remove("audio-active");
  } finally {
    // Small delay to prevent rapid double-clicks causing race conditions
    setTimeout(() => {
      isStartingAudio = false;
      startAudioButton.disabled = false;
      console.log("Audio toggle process complete. is_audio =", is_audio);
    }, 300);
  }
});

// Audio recorder handler
function audioRecorderHandler(pcmData) {
  if (websocket && websocket.readyState === WebSocket.OPEN && is_audio) {
    // Send audio as binary WebSocket frame (more efficient than base64 JSON)
    websocket.send(pcmData);
    console.log("[CLIENT TO AGENT] Sent audio chunk: %s bytes", pcmData.byteLength);
  }
}

// ============================================================
// NOTIFICATION POLLING — Calendar Watchdog proactive alerts
// ============================================================

const notificationBanner = document.getElementById('notificationBanner');
const notificationTitle = document.getElementById('notificationTitle');
const notificationMessage = document.getElementById('notificationMessage');
const dismissNotificationBtn = document.getElementById('dismissNotification');

let currentNotificationId = null;

async function pollNotifications() {
  try {
    const res = await fetch('/notifications');
    if (!res.ok) return;
    const data = await res.json();
    const notifications = data.notifications || [];

    if (notifications.length > 0) {
      const latest = notifications[0];

      // Only show if it's a new notification
      if (latest.id !== currentNotificationId) {
        currentNotificationId = latest.id;
        notificationTitle.textContent = latest.title || 'Reminder';
        notificationMessage.textContent = latest.message || '';
        notificationBanner.style.display = 'flex';

        // Log to console panel so judges can see the event
        addConsoleEntry('incoming', `Watchdog Alert: "${latest.message}"`, latest, '🔔', 'system');
      }
    } else {
      // No unread notifications — hide banner if it was visible
      if (currentNotificationId) {
        currentNotificationId = null;
        notificationBanner.style.display = 'none';
      }
    }
  } catch (e) {
    // Silently ignore polling errors (network offline, etc.)
  }
}

dismissNotificationBtn.addEventListener('click', async () => {
  notificationBanner.style.display = 'none';
  if (currentNotificationId) {
    try {
      await fetch(`/notifications/${currentNotificationId}`, { method: 'DELETE' });
    } catch (e) { /* ignore */ }
    currentNotificationId = null;
  }
});

// Start polling immediately, then every 10 seconds
pollNotifications();
setInterval(pollNotifications, 10000);

// --- TTS Toggle Management ---

const ttsToggleBtn = document.getElementById('ttsToggle');
const ttsLabel = ttsToggleBtn.querySelector('.tts-label');
const ttsIcon = ttsToggleBtn.querySelector('.material-symbols-rounded');

// Initialize UI from state
if (!ttsEnabled) {
  ttsToggleBtn.classList.remove('active');
  ttsLabel.textContent = 'Voice Off';
  ttsIcon.textContent = 'volume_off';
}

ttsToggleBtn.addEventListener('click', () => {
  ttsEnabled = !ttsEnabled;
  localStorage.setItem('ttsEnabled', ttsEnabled);
  
  if (ttsEnabled) {
    ttsToggleBtn.classList.add('active');
    ttsLabel.textContent = 'Voice On';
    ttsIcon.textContent = 'volume_up';
  } else {
    ttsToggleBtn.classList.remove('active');
    ttsLabel.textContent = 'Voice Off';
    ttsIcon.textContent = 'volume_off';
    
    // Stop any currently playing audio on the frontend immediately
    if (audioPlayerNode) {
      audioPlayerNode.port.postMessage(new Float32Array(0)); // Depending on the AudioWorklet implementation, sending empty or a specific control message stops it. Just cutting off incoming feed stops new audio.
      // Clear speaking animation
      document.querySelectorAll('.ema-speaking').forEach(el => el.classList.remove('ema-speaking'));
    }
  }

  // Notify backend
  syncTtsPreference();
});

function syncTtsPreference() {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(JSON.stringify({
      tts_preference: ttsEnabled
    }));
  }
}

// ==========================================
// EMA Grid WebSocket and Dashboard Logic
// ==========================================

let gridWebsocket = null;
let currentGridMessageId = null;
let currentGridBubbleElement = null;
let currentGridBubbleText = '';
let currentGridBubbleAuthor = null;

const gridMessagesDiv = document.getElementById("gridMessages");
const gridMessageForm = document.getElementById("gridMessageForm");
const gridMessageInput = document.getElementById("gridMessage");
const hotspotListDiv = document.getElementById("hotspotList");
const alertListDiv = document.getElementById("alertList");

function getGridWebSocketUrl() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return wsProtocol + "//" + window.location.host + "/ws/grid/" + userId + "/" + sessionId;
}

function connectGridWebsocket() {
  const ws_url = getGridWebSocketUrl();
  gridWebsocket = new WebSocket(ws_url);

  gridWebsocket.onopen = function () {
    console.log("Grid WebSocket connection opened.");
    addGridSystemMessage("Connected to EMA Grid Decision Server");
    addConsoleEntry('incoming', 'Grid WebSocket Connected', { url: ws_url }, '🔌', 'system', false, true);
    gridWebsocket.send(JSON.stringify({
      type: "text",
      text: "__START_SESSION__"
    }));
  };

  gridWebsocket.onmessage = function (event) {
    const adkEvent = JSON.parse(event.data);
    
    // Log Grid event to grid console tab
    let eventSummary = 'Event';
    let eventEmoji = '📨';
    const author = adkEvent.author || 'system';

    if (adkEvent.turnComplete) {
      eventSummary = 'Turn Complete';
      eventEmoji = '✅';
    } else if (adkEvent.content && adkEvent.content.parts) {
      let hasToolCall = false;
      for (const part of adkEvent.content.parts) {
        if (part.functionCall) {
          eventSummary = `Tool Call: ${part.functionCall.name}`;
          eventEmoji = '🛠️';
          hasToolCall = true;
          break;
        }
      }
      if (!hasToolCall) {
        eventSummary = 'Agent Thought/Speech';
        eventEmoji = '🗣️';
      }
    } else if (adkEvent.toolResponse) {
      eventSummary = 'Tool Response';
      eventEmoji = '📥';
    }

    addConsoleEntry('incoming', eventSummary, adkEvent, eventEmoji, author, false, true);
    
    if (adkEvent.turnComplete) {
      if (currentGridBubbleElement) {
        const prevIndicator = currentGridBubbleElement.querySelector('.typing-indicator');
        if (prevIndicator) prevIndicator.remove();
        updateMessageBubble(currentGridBubbleElement, currentGridBubbleText, false);
      }
      currentGridMessageId = null;
      currentGridBubbleElement = null;
      currentGridBubbleText = '';
      currentGridBubbleAuthor = null;
      return;
    }

    if (adkEvent.content && adkEvent.content.parts) {
      for (const part of adkEvent.content.parts) {
        if (part.text) {
          if (part.thought) continue;
          
          const eventAuthor = adkEvent.author || 'agent';
          
          if (currentGridBubbleElement && currentGridBubbleAuthor !== eventAuthor) {
            const prevIndicator = currentGridBubbleElement.querySelector('.typing-indicator');
            if (prevIndicator) prevIndicator.remove();
            currentGridMessageId = null;
            currentGridBubbleElement = null;
            currentGridBubbleText = '';
          }
          
          if (currentGridMessageId == null) {
            currentGridMessageId = Math.random().toString(36).substring(7);
            currentGridBubbleAuthor = eventAuthor;
            currentGridBubbleText = part.text;
            currentGridBubbleElement = createMessageBubble(currentGridBubbleText, false, true);
            currentGridBubbleElement.id = currentGridMessageId;
            gridMessagesDiv.appendChild(currentGridBubbleElement);
          } else {
            currentGridBubbleText += part.text;
            updateMessageBubble(currentGridBubbleElement, currentGridBubbleText, true);
          }
          
          scrollGridToBottom();
        }
      }
    }
  };

  gridWebsocket.onclose = function () {
    console.log("Grid WebSocket connection closed. Retrying in 5 seconds...");
    addGridSystemMessage("Disconnected from Grid Server. Reconnecting...");
    addConsoleEntry('error', 'Grid WebSocket Disconnected', {}, '🔌', 'system', false, true);
    setTimeout(connectGridWebsocket, 5000);
  };
}

function addGridSystemMessage(text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = "message system";
  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "bubble system-bubble";
  bubbleDiv.textContent = text;
  msgDiv.appendChild(bubbleDiv);
  gridMessagesDiv.appendChild(msgDiv);
  scrollGridToBottom();
}

function scrollGridToBottom() {
  if (gridMessagesDiv) {
    gridMessagesDiv.scrollTop = gridMessagesDiv.scrollHeight;
  }
}

if (gridMessageForm) {
  gridMessageForm.onsubmit = function (e) {
    e.preventDefault();
    const message = gridMessageInput.value.trim();
    if (message && gridWebsocket && gridWebsocket.readyState === WebSocket.OPEN) {
      // Add user message bubble
      const userBubble = createMessageBubble(message, true, false);
      gridMessagesDiv.appendChild(userBubble);
      scrollGridToBottom();
      
      // Reset state for new turn
      currentGridMessageId = null;
      currentGridBubbleElement = null;
      currentGridBubbleText = '';
      currentGridBubbleAuthor = null;
      
      // Log user message event
      addConsoleEntry('outgoing', 'User Message: ' + message, null, '💬', 'user', false, true);
      
      // Clear input
      gridMessageInput.value = "";
      
      // Send
      gridWebsocket.send(JSON.stringify({
        type: "text",
        text: message
      }));
    }
  };
}

// Polling BigQuery dashboard metrics
async function pollDashboard() {
  try {
    const res = await fetch("/api/grid/dashboard");
    const data = await res.json();
    
    // Render Hotspots
    if (data.telemetry && data.telemetry.length > 0) {
      hotspotListDiv.innerHTML = data.telemetry.slice(0, 5).map(item => `
        <div class="hotspot-item">
          <span class="hotspot-region">${item.region} (${item.symptom_cluster})</span>
          <span class="hotspot-cases">${item.cases} cases</span>
        </div>
      `).join("");
    } else {
      hotspotListDiv.innerHTML = "No recent hotspots reported.";
    }
    
    // Render Alerts
    if (data.staffing_alerts && data.staffing_alerts.length > 0) {
      alertListDiv.innerHTML = data.staffing_alerts.map(item => `
        <div class="staffing-alert ${item.status}">
          <span class="alert-status ${item.status}">${item.status}</span>
          <p style="margin: 0; font-size: 0.8rem; font-weight: 500;">${item.region}</p>
          <p style="margin: 0.125rem 0 0; font-size: 0.75rem; color: #5f6368;">${item.message}</p>
        </div>
      `).join("");
    } else {
      alertListDiv.innerHTML = "All regions staffing stable.";
    }
  } catch (e) {
    console.error("Error polling dashboard:", e);
  }
}

// Start Grid WebSocket and Dashboard Polling
connectGridWebsocket();
pollDashboard();
setInterval(pollDashboard, 10000);

// ==========================================
// Collapsible Header and Console Handlers
// ==========================================

const toggleHeaderBtn = document.getElementById("toggleHeaderBtn");
const toggleHeaderIcon = document.getElementById("toggleHeaderIcon");
const appHeader = document.querySelector("header");

if (toggleHeaderBtn && appHeader) {
  toggleHeaderBtn.addEventListener("click", () => {
    const isMinimized = appHeader.classList.toggle("minimized");
    toggleHeaderIcon.textContent = isMinimized ? "keyboard_arrow_down" : "keyboard_arrow_up";
    toggleHeaderBtn.title = isMinimized ? "Expand Header" : "Minimize Header";
  });
}

const toggleConsoleBtn = document.getElementById("toggleConsoleBtn");
const toggleConsoleIcon = document.getElementById("toggleConsoleIcon");
const bottomConsolePanel = document.querySelector(".console-panel");

if (toggleConsoleBtn && bottomConsolePanel) {
  toggleConsoleBtn.addEventListener("click", () => {
    const isCollapsed = bottomConsolePanel.classList.toggle("collapsed");
    toggleConsoleIcon.textContent = isCollapsed ? "keyboard_arrow_up" : "keyboard_arrow_down";
    toggleConsoleBtn.title = isCollapsed ? "Expand Console" : "Collapse Console";
    if (!isCollapsed) {
      consoleContent.scrollTop = consoleContent.scrollHeight;
    }
  });
}

// ==========================================
// Project Intro Modal Handlers (Pager/Slider)
// ==========================================

const introModal = document.getElementById("introModal");
const closeIntroModal = document.getElementById("closeIntroModal");
const prevSlideBtn = document.getElementById("prevSlideBtn");
const nextSlideBtn = document.getElementById("nextSlideBtn");
const slides = document.querySelectorAll(".intro-slide");
const dots = document.querySelectorAll(".slide-indicators .dot");

let currentSlideIdx = 0;

function showSlide(idx) {
  console.log("showSlide called with index:", idx);
  
  // Explicitly update slides
  slides.forEach((slide, i) => {
    if (i === idx) {
      slide.classList.add("active");
    } else {
      slide.classList.remove("active");
    }
    console.log(`Slide ${i} active class status:`, slide.classList.contains("active"));
  });
  
  // Explicitly update dots
  dots.forEach((dot, i) => {
    if (i === idx) {
      dot.classList.add("active");
    } else {
      dot.classList.remove("active");
    }
    console.log(`Dot ${i} active class status:`, dot.classList.contains("active"));
  });
  
  // Show/hide back button
  if (prevSlideBtn) {
    prevSlideBtn.style.display = idx === 0 ? "none" : "block";
  }
  
  // Update next button label
  if (nextSlideBtn) {
    if (idx === slides.length - 1) {
      nextSlideBtn.textContent = "Start Demo";
    } else {
      nextSlideBtn.textContent = "Next";
    }
  }
  currentSlideIdx = idx;
}

if (introModal) {
  const closeModal = () => {
    introModal.style.display = "none";
  };
  
  if (closeIntroModal) {
    closeIntroModal.addEventListener("click", closeModal);
  }
  
  if (nextSlideBtn) {
    nextSlideBtn.addEventListener("click", () => {
      if (currentSlideIdx < slides.length - 1) {
        showSlide(currentSlideIdx + 1);
      } else {
        closeModal();
      }
    });
  }
  
  if (prevSlideBtn) {
    prevSlideBtn.addEventListener("click", () => {
      if (currentSlideIdx > 0) {
        showSlide(currentSlideIdx - 1);
      }
    });
  }
  
  // Allow clicking indicators directly
  dots.forEach((dot, idx) => {
    dot.addEventListener("click", () => {
      showSlide(idx);
    });
  });
  
  // Close on background overlay click
  introModal.addEventListener("click", (e) => {
    if (e.target === introModal) {
      closeModal();
    }
  });
}
