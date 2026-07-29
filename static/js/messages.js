// Global state
let currentConversation = null;
let allConversations = [];
let messageRefreshInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadConversations();
    setupEventListeners();
    // Refresh conversations every 3 seconds
    setInterval(loadConversations, 3000);
});

// Setup event listeners
function setupEventListeners() {
    const messageInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const searchInput = document.getElementById('conversation-search');

    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    if (messageInput) {
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', filterConversations);
    }
}

// Load conversation list
async function loadConversations() {
    try {
        const response = await fetch('/messages/conversations');
        if (!response.ok) throw new Error('Failed to load conversations');

        const conversations = await response.json();
        allConversations = conversations;
        renderConversationList(conversations);
    } catch (error) {
        console.error('Error loading conversations:', error);
    }
}

// Render conversation list
function renderConversationList(conversations) {
    const container = document.getElementById('conversation-list');

    if (!conversations || conversations.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted p-3">
                <p><i class="fas fa-inbox"></i></p>
                <small>No conversations yet</small>
            </div>
        `;
        return;
    }

    container.innerHTML = conversations.map(conv => {
        const isActive = currentConversation === conv.person ? 'active' : '';
        const initials = conv.person.substring(0, 2).toUpperCase();
        const preview = conv.last_message ? conv.last_message.substring(0, 40) + '...' : 'No messages';
        const timestamp = formatTime(conv.last_timestamp);

        return `
            <div class="conversation ${isActive}" onclick="openConversation('${conv.person}')">
                <div class="conversation-avatar">${initials}</div>
                <div class="conversation-info">
                    <div class="conversation-name">${conv.person}</div>
                    <div class="conversation-preview">${preview}</div>
                </div>
                <div class="conversation-time">${timestamp}</div>
            </div>
        `;
    }).join('');
}

// Open a conversation
async function openConversation(person) {
    currentConversation = person;
    renderConversationList(allConversations);
    updateChatHeader(person);
    loadMessages(person);
    setupMessageRefresh(person);
}

// Update chat header with conversation info
function updateChatHeader(person) {
    const chatHeader = document.getElementById('chat-header');
    chatHeader.innerHTML = `
        <div class="chat-header-info">
            <div class="chat-header-name"><i class="fas fa-user-circle"></i> ${person}</div>
            <div class="chat-header-status">Active now</div>
        </div>
    `;
}

// Load messages for a conversation
async function loadMessages(person) {
    try {
        const response = await fetch(`/messages/${person}`);
        if (!response.ok) throw new Error('Failed to load messages');

        const messages = await response.json();
        renderMessages(messages, person);
        scrollToBottom();
    } catch (error) {
        console.error('Error loading messages:', error);
    }
}

// Render messages
function renderMessages(messages, person) {
    const container = document.getElementById('messages-area');
    const messagesContainer = document.getElementById('messages-container');

    // Show the messages container
    messagesContainer.style.display = 'flex';

    if (!messages || messages.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted mt-5">
                <p><i class="fas fa-comments"></i></p>
                <p>No messages yet. Start the conversation!</p>
            </div>
        `;
        return;
    }

    container.innerHTML = messages.map(msg => {
        const isSender = msg[0]; // sender
        const messageText = msg[1]; // message
        const timestamp = msg[2]; // timestamp
        const formattedTime = formatMessageTime(timestamp);
        const isMe = isSender === getCurrentUsername();

        return `
            <div class="message ${isMe ? "me" : "them"}">
            <div class="message-content">
                <div class="message-bubble">${escapeHtml(messageText)}</div>
                <div class="message-time">${formattedTime}</div>
            </div>
            </div>
        `;
    }).join('');
}

// Send a message
async function sendMessage() {
    if (!currentConversation) {
        alert('Please select a conversation first');
        return;
    }

    const input = document.getElementById('message-input');
    const message = input.value.trim();

    if (!message) {
        return;
    }

    try {
        const response = await fetch('/messages/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                recipient: currentConversation,
                message: message
            })
        });

        if (!response.ok) throw new Error('Failed to send message');

        const result = await response.json();
        if (result.status === 'success') {
            input.value = '';
            loadMessages(currentConversation);
        }
    } catch (error) {
        console.error('Error sending message:', error);
        alert('Failed to send message');
    }
}

// Setup auto-refresh for current conversation
function setupMessageRefresh(person) {
    if (messageRefreshInterval) {
        clearInterval(messageRefreshInterval);
    }
    // Refresh messages every 2 seconds
    messageRefreshInterval = setInterval(() => {
        if (currentConversation === person) {
            loadMessages(person);
        }
    }, 2000);
}

// Filter conversations by search
function filterConversations() {
    const searchInput = document.getElementById('conversation-search');
    const searchTerm = searchInput.value.toLowerCase();

    const filtered = allConversations.filter(conv =>
        conv.person.toLowerCase().includes(searchTerm) ||
        (conv.last_message && conv.last_message.toLowerCase().includes(searchTerm))
    );

    renderConversationList(filtered);
}

// Format time for conversation list
function formatTime(timestamp) {
    if (!timestamp) return '';

    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Now';
    if (diffMins < 60) return `${diffMins}m`;
    if (diffHours < 24) return `${diffHours}h`;
    if (diffDays < 7) return `${diffDays}d`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// Format time for individual messages
function formatMessageTime(timestamp) {
    if (!timestamp) return '';

    const date = new Date(timestamp);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${hours}:${minutes}`;
}

// Scroll to bottom of messages
function scrollToBottom() {
    const container = document.getElementById('messages-area');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

// Get current username from page
function getCurrentUsername() {
    // This will be replaced with actual username from session
    const userElement = document.querySelector('.navbar-brand');
    const text = userElement ? userElement.textContent : '';
    // Extract username from "Agri-Direct Messenger" - should come from session elsewhere
    // For now, we'll rely on the backend to provide context
    return sessionStorage.getItem('username') || '';
}

// Get current username from session (called on page load)
async function initializeCurrentUser() {
    try {
        const response = await fetch('/api/current-user');
        if (response.ok) {
            const data = await response.json();
            sessionStorage.setItem('username', data.username);
        }
    } catch (error) {
        console.error('Error getting current user:', error);
    }
}

// HTML escape utility
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// Initialize current user on page load
initializeCurrentUser();
