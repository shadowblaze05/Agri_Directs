// Global state
let currentConversation = null;
let allConversations = [];
let messageRefreshInterval = null;
let searchTimeout = null;
let hasLoadedConversations = false;
let messagesLoadedFor = null;
let messagesAttemptedFor = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadConversations();
    loadNotifications();
    setupEventListeners();
    // Refresh conversations every 3 seconds
    setInterval(loadConversations, 3000);
    setInterval(loadNotifications, 10000);
});

async function loadNotifications() {
    const notificationList = document.getElementById('notification-list');
    const notificationCount = document.getElementById('notification-count');
    if (!notificationList || !notificationCount) return;

    try {
        const [notificationsResponse, countResponse] = await Promise.all([
            fetch('/notifications'),
            fetch('/notifications/unread-count')
        ]);
        if (!notificationsResponse.ok || !countResponse.ok) {
            throw new Error('Failed to load notifications');
        }

        const notifications = await notificationsResponse.json();
        const countData = await countResponse.json();
        const unreadCount = Number(countData.unread_count || 0);
        notificationCount.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
        notificationCount.classList.toggle('d-none', unreadCount === 0);

        notificationList.replaceChildren();
        const heading = document.createElement('li');
        heading.className = 'dropdown-header';
        heading.textContent = 'Notifications';
        notificationList.append(heading);

        if (!notifications.length) {
            const emptyItem = document.createElement('li');
            const emptyMessage = document.createElement('span');
            emptyMessage.className = 'dropdown-item text-muted';
            emptyMessage.textContent = 'No notifications';
            emptyItem.append(emptyMessage);
            notificationList.append(emptyItem);
        } else {
            notifications.slice(0, 5).forEach((notification) => {
                const item = document.createElement('li');
                const link = document.createElement('a');
                const href = notification.link;
                link.className = 'dropdown-item text-wrap';
                link.href = typeof href === 'string' && href.startsWith('/') && !href.startsWith('//')
                    ? href
                    : '/notifications-center';
                if (!notification.is_read) link.classList.add('fw-bold');
                const title = document.createElement('span');
                title.className = 'd-block';
                title.textContent = notification.title || 'Update';
                const message = document.createElement('small');
                message.className = 'text-muted';
                message.textContent = notification.message || '';
                link.append(title, message);
                item.append(link);
                notificationList.append(item);
            });
        }

        const footer = document.createElement('li');
        const allNotifications = document.createElement('a');
        allNotifications.className = 'dropdown-item text-center text-success';
        allNotifications.href = '/notifications-center';
        allNotifications.textContent = 'View all notifications';
        footer.append(allNotifications);
        notificationList.append(footer);
    } catch (error) {
        console.error('Failed to load notifications:', error);
    }
}

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
        searchInput.addEventListener('input', () => {
            if (searchTimeout) clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => filterConversations(), 250);
        });
    }
}

// Load conversation list
async function loadConversations() {
    const container = document.getElementById('conversation-list');
    if (!container) return;

    if (!hasLoadedConversations) {
        container.innerHTML = `
            <div class="page-state skeleton" style="min-height: 120px; padding: 1.25rem;" role="status" aria-live="polite">
                <div class="state-icon"><i class="fas fa-spinner fa-spin"></i></div>
                <h6 class="state-title">Loading conversations</h6>
                <p class="state-description">Checking recent messages.</p>
            </div>
        `;
    }

    try {
        const response = await fetch('/messages/conversations');
        if (!response.ok) throw new Error('Failed to load conversations');

        const conversations = await response.json();
        allConversations = conversations;
        hasLoadedConversations = true;
        renderConversationList(conversations);
    } catch (error) {
        console.error('Error loading conversations:', error);
        if (!hasLoadedConversations) {
            container.innerHTML = `
                <div class="page-state" style="min-height: 120px; padding: 1.25rem;" role="alert">
                    <div class="state-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <h6 class="state-title">Unable to load conversations</h6>
                    <p class="state-description">Check your connection and try again.</p>
                    <button type="button" class="btn btn-sm btn-outline-success" onclick="loadConversations()">Try again</button>
                </div>
            `;
        }
    }
}

// Render conversation list
function renderConversationList(conversations) {
    const container = document.getElementById('conversation-list');

    if (!conversations || conversations.length === 0) {
        container.innerHTML = `
            <div class="page-state" style="min-height: 120px; padding: 1.25rem;">
                <div class="state-icon"><i class="fas fa-inbox"></i></div>
                <h6 class="state-title">No conversations yet</h6>
                <p class="state-description">Start a chat to begin messaging.</p>
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
    if (currentConversation !== person) {
        messagesLoadedFor = null;
        messagesAttemptedFor = null;
    }
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
    const container = document.getElementById('messages-area');
    const messagesContainer = document.getElementById('messages-container');
    if (currentConversation === person && messagesAttemptedFor !== person) {
        messagesContainer.style.display = 'flex';
        container.innerHTML = `
            <div class="page-state skeleton" role="status" aria-live="polite">
                <div class="state-icon"><i class="fas fa-spinner fa-spin"></i></div>
                <h6 class="state-title">Loading messages</h6>
                <p class="state-description">Opening this conversation.</p>
            </div>
        `;
        messagesAttemptedFor = person;
    }

    try {
        const response = await fetch(`/messages/${person}`);
        if (!response.ok) throw new Error('Failed to load messages');

        const messages = await response.json();
        if (currentConversation !== person) return;
        messagesLoadedFor = person;
        renderMessages(messages, person);
        scrollToBottom();
    } catch (error) {
        console.error('Error loading messages:', error);
        if (currentConversation === person && messagesLoadedFor !== person) {
            messagesContainer.style.display = 'flex';
            container.innerHTML = `
                <div class="page-state" role="alert">
                    <div class="state-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <h6 class="state-title">Unable to load messages</h6>
                    <p class="state-description">Check your connection and try again.</p>
                    <button type="button" class="btn btn-sm btn-outline-success" onclick="loadMessages(currentConversation)">Try again</button>
                </div>
            `;
        }
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
async function filterConversations() {
    const searchInput = document.getElementById('conversation-search');
    const searchTerm = searchInput.value.trim().toLowerCase();

    if (!searchTerm) {
        renderConversationList(allConversations);
        return;
    }

    // Query backend for matching users
    try {
        const resp = await fetch(`/users/search?q=${encodeURIComponent(searchTerm)}`);
        if (!resp.ok) throw new Error('Search failed');
        const users = await resp.json(); // array of usernames

        // Build display list: prefer existing conversations (with last_message), otherwise show 'No messages'
        const results = users.map(u => {
            const found = allConversations.find(c => (c.person || '') === u);
            if (found) return found;
            return { person: u, last_message: null, last_timestamp: null };
        });

        renderConversationList(results);
    } catch (e) {
        console.error('User search error', e);
        renderConversationList([]);
    }
}

// Format time for conversation list
function formatTime(timestamp) {
    const date = parseMessageTimestamp(timestamp);
    if (!date) return '';

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
    const date = parseMessageTimestamp(timestamp);
    if (!date) return '';

    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${hours}:${minutes}`;
}

// PostgreSQL stores legacy message timestamps as "YYYY-MM-DD HH:MM:SS[.ffffff]".
// Normalizing the separator makes the value valid ISO-8601 for browser parsing.
function parseMessageTimestamp(timestamp) {
    if (!timestamp) return null;

    const value = typeof timestamp === 'string'
        ? timestamp.trim().replace(/^(\d{4}-\d{2}-\d{2})\s+/, '$1T')
        : timestamp;
    const date = new Date(value);

    return Number.isNaN(date.getTime()) ? null : date;
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
