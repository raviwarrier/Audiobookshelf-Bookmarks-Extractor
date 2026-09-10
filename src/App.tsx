import React, { useState, useCallback } from 'react';
import { Navbar } from './components/Navbar';
import { CaptureView } from './components/CaptureView';
import { SnippetsView } from './components/SnippetsView';
import { AuthModal } from './components/AuthModal';
import { AbsUser, AbsActiveSession, Snippet } from './types';
import { wipeSessionKey } from './lib/crypto';
import { authenticateAbs, fetchActiveSession } from './lib/absClient';

// Initial sample snippets to demonstrate library structure
const INITIAL_SNIPPETS: Snippet[] = [
  {
    id: 'dune-sample-01',
    bookTitle: 'Dune',
    author: 'Frank Herbert',
    chapterName: 'Chapter 03 - Gom Jabbar',
    timestamp: '20260909_141020',
    startTime: 820,
    duration: 60,
    audioUrl: 'https://cdn.freesound.org/previews/612/612089_5674468-lq.mp3',
    transcript: 'I must not fear. Fear is the mind-killer. Fear is the little-death that brings total obliteration. I will face my fear. I will permit it to pass over me and through me.',
    markdownContent: `---
title: "Dune"
author: "Frank Herbert"
chapter: "Chapter 03 - Gom Jabbar"
timestamp: "20260909_141020"
current_time: 850
start_time: 820
duration: 60
---

# Dune

- **Author:** Frank Herbert
- **Chapter:** Chapter 03 - Gom Jabbar
- **Offset:** 820s (Duration: 60s)

## Transcript

I must not fear. Fear is the mind-killer. Fear is the little-death that brings total obliteration. I will face my fear. I will permit it to pass over me and through me.
`,
    createdAt: Date.now() - 3600000 * 2,
    username: 'abs_user',
  },
  {
    id: 'atomic-habits-sample-02',
    bookTitle: 'Atomic Habits',
    author: 'James Clear',
    chapterName: 'Chapter 01 - The Surprising Power of Atomic Habits',
    timestamp: '20260909_120530',
    startTime: 340,
    duration: 45,
    audioUrl: 'https://cdn.freesound.org/previews/612/612089_5674468-lq.mp3',
    transcript: 'You do not rise to the level of your goals. You fall to the level of your systems. Your goal is your desired outcome, but your system is the collection of daily habits that will get you there.',
    markdownContent: `---
title: "Atomic Habits"
author: "James Clear"
chapter: "Chapter 01 - The Surprising Power of Atomic Habits"
timestamp: "20260909_120530"
current_time: 370
start_time: 340
duration: 45
---

# Atomic Habits

- **Author:** James Clear
- **Chapter:** Chapter 01 - The Surprising Power of Atomic Habits
- **Offset:** 340s (Duration: 45s)

## Transcript

You do not rise to the level of your goals. You fall to the level of your systems. Your goal is your desired outcome, but your system is the collection of daily habits that will get you there.
`,
    createdAt: Date.now() - 3600000 * 18,
    username: 'abs_user',
  },
];

export function App() {
  const [activeView, setActiveView] = useState<'capture' | 'library'>('capture');
  
  // Single-session in-memory credentials & connection state (never stored to disk/localStorage)
  const [user, setUser] = useState<AbsUser | null>(null);
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string>('https://books.raviwarrier.net');
  const [sidecarUrl, setSidecarUrl] = useState<string>('http://[your ip:port/proxied url]');
  const [useProxy, setUseProxy] = useState<boolean>(true);

  // Active Listening Session
  const [session, setSession] = useState<AbsActiveSession | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Auth modal opens automatically on initial app load if no active user session exists
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(true);

  // Snippets library state
  const [snippets, setSnippets] = useState<Snippet[]>(INITIAL_SNIPPETS);
  const [isLoadingBookmarks, setIsLoadingBookmarks] = useState<boolean>(false);

  // Sync user's bookmarks from sidecar's {username}/bookmarks directory
  const syncUserBookmarks = useCallback(async (
    targetSidecar: string,
    token: string,
    username: string,
    proxyEnabled: boolean
  ) => {
    setIsLoadingBookmarks(true);
    try {
      const endpoint = `${targetSidecar.replace(/\/+$/, '')}/api/user/bookmarks`;
      if (proxyEnabled) {
        const res = await fetch('/api/proxy/abs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            targetUrl: endpoint,
            method: 'GET',
            headers: { 'Authorization': `Bearer ${token}` }
          })
        });
        const json = await res.json();
        if (json.ok && json.data && Array.isArray(json.data.bookmarks)) {
          const sidecarBookmarks: Snippet[] = json.data.bookmarks.map((b: any) => ({
            id: b.id || `b-${b.timestamp}`,
            bookTitle: b.book_title,
            author: b.author,
            chapterName: b.chapter,
            timestamp: b.timestamp,
            startTime: b.start_time,
            duration: b.duration,
            audioUrl: b.audio_url ? (b.audio_url.startsWith('http') ? b.audio_url : `${targetSidecar.replace(/\/+$/, '')}${b.audio_url}`) : '',
            transcript: b.transcript,
            markdownContent: `# ${b.book_title}\n\n${b.transcript}`,
            createdAt: b.created_at ? new Date(b.created_at).getTime() : Date.now(),
            username: b.username || username
          }));
          if (sidecarBookmarks.length > 0) {
            setSnippets(prev => {
              const otherUsers = prev.filter(s => s.username && s.username !== username);
              return [...sidecarBookmarks, ...otherUsers];
            });
          }
        }
      } else {
        const res = await fetch(endpoint, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.bookmarks)) {
            const sidecarBookmarks: Snippet[] = data.bookmarks.map((b: any) => ({
              id: b.id || `b-${b.timestamp}`,
              bookTitle: b.book_title,
              author: b.author,
              chapterName: b.chapter,
              timestamp: b.timestamp,
              startTime: b.start_time,
              duration: b.duration,
              audioUrl: b.audio_url ? (b.audio_url.startsWith('http') ? b.audio_url : `${targetSidecar.replace(/\/+$/, '')}${b.audio_url}`) : '',
              transcript: b.transcript,
              markdownContent: `# ${b.book_title}\n\n${b.transcript}`,
              createdAt: b.created_at ? new Date(b.created_at).getTime() : Date.now(),
              username: b.username || username
            }));
            if (sidecarBookmarks.length > 0) {
              setSnippets(prev => {
                const otherUsers = prev.filter(s => s.username && s.username !== username);
                return [...sidecarBookmarks, ...otherUsers];
              });
            }
          }
        }
      }
    } catch (err) {
      console.warn('Sidecar bookmarks sync notice:', err);
    } finally {
      setIsLoadingBookmarks(false);
    }
  }, []);

  // Automatically fetch active listening session once user connects
  const loadActiveSession = useCallback(async (
    targetServer: string,
    token: string,
    proxyEnabled: boolean
  ) => {
    setIsLoadingSession(true);
    setSessionError(null);
    try {
      const active = await fetchActiveSession(targetServer, token, proxyEnabled);
      setSession(active);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not fetch active listening session';
      setSessionError(msg);
    } finally {
      setIsLoadingSession(false);
    }
  }, []);

  // Handle connection from Auth Modal
  const handleConnect = async (params: {
    serverUrl: string;
    sidecarUrl: string;
    useProxy: boolean;
    authMode: 'token' | 'userpass';
    token?: string;
    username?: string;
    password?: string;
    isMock?: boolean;
  }) => {
    setServerUrl(params.serverUrl);
    setSidecarUrl(params.sidecarUrl);
    setUseProxy(params.useProxy);

    if (params.isMock) {
      // Mock session for exploratory demo
      const mockUser = { id: 'usr_mock', username: 'bookworm_user' };
      setUser(mockUser);
      setActiveToken('mock_token_demo');
      setSession({
        libraryItemId: 'li_sample_project_hail_mary',
        bookTitle: 'Project Hail Mary',
        author: 'Andy Weir',
        chapterName: 'Chapter 04 - Laboratory Discovery',
        currentTime: 1420,
        duration: 36000,
        audioFilePath: '/audiobooks/Andy Weir/Project Hail Mary/Project_Hail_Mary_Part01.m4b',
      });
      setSessionError(null);
      setIsAuthModalOpen(false);
      return;
    }

    // Live authentication against Audiobookshelf
    const authResult = await authenticateAbs(
      params.serverUrl,
      params.authMode,
      params.token,
      params.username,
      params.password,
      params.useProxy
    );

    setUser(authResult.user);
    setActiveToken(authResult.token);
    setIsAuthModalOpen(false);

    // Automatically load the active listening session and sync bookmarks in background
    loadActiveSession(params.serverUrl, authResult.token, params.useProxy);
    syncUserBookmarks(params.sidecarUrl, authResult.token, authResult.user.username, params.useProxy);
  };

  // Re-sync session playback position on demand
  const handleRefreshSession = async () => {
    if (!activeToken) return;
    await loadActiveSession(serverUrl, activeToken, useProxy);
  };

  // Wipes all in-memory credentials immediately
  const handleWipeSession = () => {
    setUser(null);
    setActiveToken(null);
    setSession(null);
    setSessionError(null);
    wipeSessionKey();
    setIsAuthModalOpen(true);
  };

  const handleSnippetCreated = (newSnippet: Snippet) => {
    setSnippets((prev) => [newSnippet, ...prev]);
  };

  const handleDeleteSnippet = (id: string) => {
    setSnippets((prev) => prev.filter((s) => s.id !== id));
  };

  return (
    <div className="min-h-screen bg-[#050505] text-neutral-200 font-mono flex flex-col">
      {/* Navigation Header */}
      <Navbar
        activeView={activeView}
        onViewChange={setActiveView}
        user={user}
        snippetCount={snippets.length}
        onOpenAuthModal={() => setIsAuthModalOpen(true)}
        onWipeSession={handleWipeSession}
      />

      {/* Main View Container */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-4 md:p-8">
        {activeView === 'capture' ? (
          <CaptureView
            user={user}
            activeToken={activeToken}
            serverUrl={serverUrl}
            sidecarUrl={sidecarUrl}
            useProxy={useProxy}
            session={session}
            isLoadingSession={isLoadingSession}
            sessionError={sessionError}
            onRefreshSession={handleRefreshSession}
            onOpenAuthModal={() => setIsAuthModalOpen(true)}
            onSnippetCreated={handleSnippetCreated}
            onNavigateToLibrary={() => setActiveView('library')}
            onUseMockSession={() => {
              handleConnect({
                serverUrl,
                sidecarUrl,
                useProxy,
                authMode: 'token',
                token: 'mock_token',
                isMock: true,
              });
            }}
          />
        ) : (
          <SnippetsView
            snippets={snippets}
            user={user}
            onDeleteSnippet={handleDeleteSnippet}
            onNavigateToCapture={() => setActiveView('capture')}
            onRefreshSnippets={async () => {
              if (activeToken && user) {
                await syncUserBookmarks(sidecarUrl, activeToken, user.username, useProxy);
              }
            }}
            isLoadingSnippets={isLoadingBookmarks}
          />
        )}
      </main>

      {/* Auth & User Switching Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        user={user}
        currentServerUrl={serverUrl}
        currentSidecarUrl={sidecarUrl}
        currentUseProxy={useProxy}
        onConnect={handleConnect}
        onDisconnect={handleWipeSession}
      />

      {/* Minimal Footer */}
      <footer className="border-t border-neutral-900 px-6 py-4 text-center text-xs text-neutral-600 font-mono">
        Audiobookshelf Bookmarks Manager • Single-Session In-Memory Security
      </footer>
    </div>
  );
}

export default App;
