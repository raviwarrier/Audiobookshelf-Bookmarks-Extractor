import React, { useState } from 'react';
import { 
  Search, 
  Download, 
  Copy, 
  Trash2, 
  Check, 
  FileText, 
  FileAudio,
  BookmarkPlus,
  FolderTree,
  User as UserIcon,
  RefreshCw,
  Sliders,
  Archive,
  AlertTriangle,
  RotateCw,
  X,
  BookOpen
} from 'lucide-react';
import { Snippet, AbsUser } from '../types';

interface SnippetsViewProps {
  snippets: Snippet[];
  user: AbsUser | null;
  activeToken?: string | null;
  serverUrl?: string;
  sidecarUrl?: string;
  useProxy?: boolean;
  onDeleteSnippet: (id: string) => void;
  onNavigateToCapture: () => void;
  onRefreshSnippets?: () => Promise<void>;
  isLoadingSnippets?: boolean;
}

export const SnippetsView: React.FC<SnippetsViewProps> = ({
  snippets,
  user,
  activeToken,
  serverUrl = 'http://localhost:13378',
  sidecarUrl = 'http://localhost:13380',
  useProxy = true,
  onDeleteSnippet,
  onNavigateToCapture,
  onRefreshSnippets,
  isLoadingSnippets = false,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Expand / Adjust Snippet Modal State
  const [expandSnippet, setExpandSnippet] = useState<Snippet | null>(null);
  const [preRoll, setPreRoll] = useState<number>(30);
  const [postRoll, setPostRoll] = useState<number>(60);
  const [isExpanding, setIsExpanding] = useState<boolean>(false);
  const [expandError, setExpandError] = useState<string | null>(null);
  const [expandSuccess, setExpandSuccess] = useState<string | null>(null);

  // Exporting state
  const [exportingBook, setExportingBook] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [selectedBookFilter, setSelectedBookFilter] = useState<string | null>(null);

  // Group snippets by unique books
  const uniqueBooks: string[] = Array.from(new Set(snippets.map((s) => s.bookTitle).filter(Boolean)));

  const filteredSnippets = snippets.filter((s) => {
    const matchesSearch =
      s.bookTitle.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.author.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.chapterName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.transcript.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesBook = !selectedBookFilter || s.bookTitle === selectedBookFilter;
    return matchesSearch && matchesBook;
  });

  const handleCopyTranscript = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDownloadMarkdown = (snippet: Snippet) => {
    const blob = new Blob([snippet.markdownContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleDownloadAudio = async (snippet: Snippet) => {
    if (!snippet.audioUrl) return;
    try {
      const res = await fetch(snippet.audioUrl);
      if (res.ok) {
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.mp3`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(blobUrl);
        return;
      }
    } catch (err) {
      console.warn('Direct blob audio download failed, falling back to direct link:', err);
    }
    const link = document.createElement('a');
    link.href = snippet.audioUrl;
    link.download = `${snippet.bookTitle.replace(/\s+/g, '_')}_${snippet.timestamp}.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Open Expand Modal with calculated current values
  const openExpandModal = (snippet: Snippet) => {
    setExpandSnippet(snippet);
    // Default pre-roll is 30s, post-roll is 60s (or based on snippet duration)
    setPreRoll(30);
    setPostRoll(Math.max(30, snippet.duration - 30));
    setExpandError(null);
    setExpandSuccess(null);
  };

  // Submit expansion to backend
  const handleExecuteExpand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!expandSnippet) return;

    setIsExpanding(true);
    setExpandError(null);
    setExpandSuccess(null);

    try {
      const payload = {
        timestamp: expandSnippet.timestamp,
        currentTime: expandSnippet.currentTime ?? (expandSnippet.startTime + expandSnippet.duration / 2),
        preRoll,
        postRoll,
        libraryItemId: expandSnippet.libraryItemId,
        bookTitle: expandSnippet.bookTitle,
        token: activeToken,
        serverUrl,
      };

      const targetEndpoint = `${sidecarUrl.replace(/\/+$/, '')}/api/snippet/expand`;

      let res: Response;
      if (useProxy) {
        res = await fetch('/api/proxy/abs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            targetUrl: targetEndpoint,
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${activeToken || ''}`,
              'X-ABS-Server-Url': serverUrl,
            },
            body: payload,
          }),
        });
      } else {
        res = await fetch(targetEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${activeToken || ''}`,
            'X-ABS-Server-Url': serverUrl,
          },
          body: JSON.stringify(payload),
        });
      }

      if (useProxy) {
        const proxyJson = await res.json();
        if (!proxyJson.ok) {
          throw new Error(proxyJson.data?.detail || proxyJson.message || 'Failed to expand snippet');
        }
      } else if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errJson.detail || 'Failed to expand snippet');
      }

      setExpandSuccess('Snippet successfully updated and re-transcribed!');
      setTimeout(() => {
        setExpandSnippet(null);
        setExpandSuccess(null);
      }, 1200);

      if (onRefreshSnippets) {
        await onRefreshSnippets();
      }
    } catch (err: unknown) {
      setExpandError(err instanceof Error ? err.message : 'Error updating snippet');
    } finally {
      setIsExpanding(false);
    }
  };

  // Export all snippets from the book (either as a ZIP containing MP3s + MDs or as a single combined MD)
  const handleExportBook = async (bookTitle: string, format: 'zip' | 'markdown') => {
    setExportingBook(bookTitle);
    setExportError(null);

    try {
      const tokenParam = activeToken ? `&token=${encodeURIComponent(activeToken)}` : '';
      const serverParam = serverUrl ? `&server_url=${encodeURIComponent(serverUrl)}` : '';
      const endpoint = `/api/export-book?book_title=${encodeURIComponent(bookTitle)}&format=${format}${tokenParam}${serverParam}`;
      const headers: Record<string, string> = {};
      if (activeToken) {
        headers['Authorization'] = `Bearer ${activeToken}`;
      }
      headers['X-ABS-Server-Url'] = serverUrl;

      const res = await fetch(endpoint, { headers });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `Export failed with status ${res.status}` }));
        throw new Error(err.detail || err.error || err.message || `Export failed with HTTP ${res.status}`);
      }

      const blob = await res.blob();
      const ext = format === 'zip' ? 'zip' : 'md';
      const safeName = bookTitle.replace(/[^a-zA-Z0-9_-]/g, '_');
      const filename = `${safeName}_All_Snippets.${ext}`;

      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(blobUrl);
    } catch (err: unknown) {
      setExportError(err instanceof Error ? err.message : 'Failed to export book snippets');
      setTimeout(() => setExportError(null), 5000);
    } finally {
      setExportingBook(null);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      
      {/* Header & Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-800 pb-4">
        <div>
          <h2 className="text-base font-semibold text-white tracking-tight uppercase">
            Saved Bookmarks & Transcripts
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            {snippets.length} audio clips & markdown files in library • Auto-synced
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative w-full sm:w-64">
            <Search className="w-3.5 h-3.5 text-neutral-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search transcripts or books..."
              className="w-full bg-[#181818] border border-neutral-700 hover:border-neutral-500 focus:border-neutral-300 focus:bg-[#202020] pl-8 pr-3 py-1.5 text-xs text-white placeholder-neutral-500 focus:outline-none transition-colors font-mono"
            />
          </div>

          {onRefreshSnippets && (
            <button
              onClick={onRefreshSnippets}
              disabled={isLoadingSnippets}
              title="Sync bookmarks from server volume"
              className="px-2.5 py-1.5 border border-neutral-700 bg-[#161616] hover:bg-[#222222] hover:border-neutral-500 text-xs text-neutral-200 transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoadingSnippets ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Sync</span>
            </button>
          )}

          <button
            onClick={onNavigateToCapture}
            className="px-3 py-1.5 bg-neutral-100 text-black hover:bg-white text-xs font-semibold flex items-center gap-1.5 shrink-0 transition-colors"
          >
            <BookmarkPlus className="w-3.5 h-3.5" />
            <span>New Snippet</span>
          </button>
        </div>
      </div>

      {/* User-specific Volume Directory Scope Banner & Book Quick-Exports */}
      <div className="flex flex-col gap-3 px-4 py-3 bg-[#0e0e0e] border border-neutral-700 text-xs text-neutral-300 font-mono">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FolderTree className="w-3.5 h-3.5 text-neutral-400" />
            <span className="text-neutral-400">Volume Storage:</span>
            <span className="text-white font-semibold">
              {user ? `${user.username}/bookmarks/` : 'username/bookmarks/'}
            </span>
            <span className="text-[10px] bg-neutral-800 text-neutral-400 px-1.5 py-0.5 border border-neutral-700">
              User Isolated
            </span>
          </div>
          {user && (
            <div className="flex items-center gap-1.5 text-neutral-400">
              <UserIcon className="w-3 h-3 text-neutral-400" />
              <span>Logged in as:</span>
              <span className="text-white font-medium">@{user.username}</span>
            </div>
          )}
        </div>

        {/* Quick Book Export Bar if books exist */}
        {uniqueBooks.length > 0 && (
          <div className="pt-2.5 border-t border-neutral-800/80 flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-neutral-400 text-[11px] shrink-0">
              <Archive className="w-3 h-3 text-neutral-400" />
              <span>Export All Snippets by Book:</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {uniqueBooks.map((bTitle) => {
                const isThisExporting = exportingBook === bTitle;
                return (
                  <div key={bTitle} className="inline-flex items-center gap-1 bg-[#161616] border border-neutral-700 px-2 py-1 text-[11px]">
                    <span className="text-neutral-200 font-medium truncate max-w-[150px] sm:max-w-[220px]" title={bTitle}>
                      {bTitle}
                    </span>
                    <span className="text-neutral-500">•</span>
                    <button
                      onClick={() => handleExportBook(bTitle, 'zip')}
                      disabled={isThisExporting}
                      title="Download complete ZIP (Audio MP3s + Markdown files)"
                      className="text-neutral-300 hover:text-white underline disabled:opacity-50 transition-colors"
                    >
                      {isThisExporting ? 'Exporting...' : 'ZIP'}
                    </button>
                    <span className="text-neutral-600">/</span>
                    <button
                      onClick={() => handleExportBook(bTitle, 'markdown')}
                      disabled={isThisExporting}
                      title="Download combined single Markdown note"
                      className="text-neutral-300 hover:text-white underline disabled:opacity-50 transition-colors"
                    >
                      Combined MD
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {exportError && (
          <div className="text-[11px] text-red-400 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>{exportError}</span>
          </div>
        )}
      </div>

      {/* Book Filter Chips (When multiple books exist) */}
      {uniqueBooks.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 pt-1 pb-1">
          <button
            onClick={() => setSelectedBookFilter(null)}
            className={`px-2.5 py-1 text-xs font-mono transition-colors border ${
              selectedBookFilter === null
                ? 'bg-neutral-200 text-black border-neutral-200 font-semibold'
                : 'bg-[#141414] text-neutral-300 border-neutral-700 hover:border-neutral-500'
            }`}
          >
            All Books ({snippets.length})
          </button>
          {uniqueBooks.map((bTitle) => {
            const count = snippets.filter((s) => s.bookTitle === bTitle).length;
            const isSelected = selectedBookFilter === bTitle;
            return (
              <button
                key={bTitle}
                onClick={() => setSelectedBookFilter(isSelected ? null : bTitle)}
                className={`px-2.5 py-1 text-xs font-mono transition-colors border truncate max-w-[260px] ${
                  isSelected
                    ? 'bg-neutral-200 text-black border-neutral-200 font-semibold'
                    : 'bg-[#141414] text-neutral-300 border-neutral-700 hover:border-neutral-500'
                }`}
                title={bTitle}
              >
                {bTitle} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Snippet List */}
      {filteredSnippets.length === 0 ? (
        <div className="border border-neutral-700 bg-[#0d0d0d] p-12 text-center space-y-4">
          <div className="text-neutral-400 text-sm font-mono">
            {searchTerm || selectedBookFilter ? 'No matching snippets found.' : 'No snippets captured yet.'}
          </div>
          <button
            onClick={onNavigateToCapture}
            className="px-4 py-2 border border-neutral-700 bg-[#161616] text-xs text-neutral-200 hover:text-white hover:border-neutral-500 transition-colors"
          >
            Go to Capture Screen →
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredSnippets.map((snippet) => (
            <article
              key={snippet.id}
              className="border border-neutral-700 bg-[#0d0d0d] p-5 space-y-4"
            >
              {/* Snippet Header */}
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2 border-b border-neutral-800 pb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    {snippet.bookTitle}
                  </h3>
                  <div className="text-xs text-neutral-400 mt-0.5 flex flex-wrap items-center gap-2">
                    <span>{snippet.author}</span>
                    <span>•</span>
                    <span>{snippet.chapterName}</span>
                    <span className="text-[10px] text-neutral-400 bg-neutral-800 px-1.5 py-0.5 border border-neutral-700">
                      @{snippet.username || user?.username || 'user'}
                    </span>
                    <span className="text-[10px] text-neutral-500 hidden sm:inline">
                      {snippet.username || user?.username || 'user'}/bookmarks/
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs text-neutral-400 font-mono self-end sm:self-auto">
                  <span>Start: {Math.round(snippet.startTime)}s</span>
                  <span>Duration: {snippet.duration}s</span>
                  <span>{new Date(snippet.createdAt).toLocaleDateString()}</span>
                </div>
              </div>

              {/* Audio Player - remounts cleanly on duration or audioUrl change to purge stale audio buffer */}
              <div className="bg-[#141414] p-2.5 border border-neutral-700">
                <audio
                  key={`${snippet.id}-${snippet.duration}-${snippet.audioUrl}`}
                  controls
                  preload="metadata"
                  src={snippet.audioUrl}
                  className="w-full h-8 bg-[#181818]"
                />
              </div>

              {/* Transcript Text Box */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-neutral-400">
                  <span className="font-mono text-[11px] uppercase">Whisper Transcript</span>
                  <button
                    onClick={() => handleCopyTranscript(snippet.id, snippet.transcript)}
                    className="flex items-center gap-1 text-neutral-300 hover:text-white transition-colors"
                  >
                    {copiedId === snippet.id ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-white" />
                        <span>Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>Copy Text</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="p-3 bg-[#151515] border border-neutral-700 text-xs text-neutral-200 leading-relaxed font-mono whitespace-pre-wrap">
                  {snippet.transcript}
                </div>
              </div>

              {/* Action Toolbar */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-neutral-800 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => handleDownloadAudio(snippet)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-neutral-700 bg-[#161616] hover:border-neutral-500 text-neutral-200 hover:text-white transition-colors"
                  >
                    <FileAudio className="w-3.5 h-3.5" />
                    <span>Download .MP3</span>
                  </button>

                  <button
                    onClick={() => handleDownloadMarkdown(snippet)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-neutral-700 bg-[#161616] hover:border-neutral-500 text-neutral-200 hover:text-white transition-colors"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>Download .MD</span>
                  </button>

                  {/* Expand / Adjust Snippet Context Button */}
                  <button
                    onClick={() => openExpandModal(snippet)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-neutral-700 bg-[#1a1a1a] hover:border-neutral-400 text-neutral-100 hover:text-white transition-colors"
                    title="Adjust pre-roll & post-roll to expand snippet context"
                  >
                    <Sliders className="w-3.5 h-3.5 text-neutral-300" />
                    <span>Adjust Duration / Context</span>
                  </button>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleExportBook(snippet.bookTitle, 'zip')}
                    disabled={exportingBook === snippet.bookTitle}
                    className="text-neutral-400 hover:text-white flex items-center gap-1 text-[11px] underline transition-colors disabled:opacity-50"
                    title="Export all snippets for this book as ZIP"
                  >
                    <Archive className="w-3 h-3" />
                    <span>Export Book ({exportingBook === snippet.bookTitle ? '...' : 'ZIP'})</span>
                  </button>

                  <button
                    onClick={() => onDeleteSnippet(snippet.id)}
                    className="text-neutral-400 hover:text-red-400 flex items-center gap-1 transition-colors"
                    title="Delete snippet"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Delete</span>
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Expand / Adjust Snippet Duration Modal */}
      {expandSnippet && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0e0e0e] border border-neutral-700 w-full max-w-md p-5 space-y-4 font-mono shadow-2xl relative">
            
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-neutral-800 pb-3">
              <div>
                <h3 className="text-sm font-semibold text-white uppercase tracking-tight flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-neutral-300" />
                  <span>Expand Snippet Context</span>
                </h3>
                <p className="text-xs text-neutral-400 mt-1 truncate max-w-xs">
                  {expandSnippet.bookTitle}
                </p>
              </div>
              <button
                onClick={() => !isExpanding && setExpandSnippet(null)}
                className="text-neutral-400 hover:text-white p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Warning Callout Box */}
            <div className="bg-amber-950/30 border border-amber-800/60 p-3 text-xs text-amber-200/90 flex items-start gap-2.5">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <span className="font-semibold text-amber-300">Replacement Notice:</span>
                <p className="text-[11px] leading-relaxed text-amber-200/80">
                  Expanding this snippet will re-clip the audio and generate a fresh Whisper transcription. The previous .MP3 and Markdown note will be replaced.
                </p>
              </div>
            </div>

            {/* Adjustment Form */}
            <form onSubmit={handleExecuteExpand} className="space-y-4 text-xs">
              <div>
                <label className="block text-neutral-300 mb-1.5">
                  Pre-Roll: <span className="text-white font-semibold">{preRoll}s</span> before bookmark anchor
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="5"
                    max="180"
                    step="5"
                    value={preRoll}
                    onChange={(e) => setPreRoll(Number(e.target.value))}
                    className="w-full accent-neutral-200 cursor-pointer"
                  />
                  <input
                    type="number"
                    min="5"
                    max="300"
                    value={preRoll}
                    onChange={(e) => setPreRoll(Math.max(5, Number(e.target.value)))}
                    className="w-16 bg-[#161616] border border-neutral-700 px-2 py-1 text-white text-center"
                  />
                </div>
              </div>

              <div>
                <label className="block text-neutral-300 mb-1.5">
                  Post-Roll: <span className="text-white font-semibold">{postRoll}s</span> after bookmark anchor
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="10"
                    max="300"
                    step="5"
                    value={postRoll}
                    onChange={(e) => setPostRoll(Number(e.target.value))}
                    className="w-full accent-neutral-200 cursor-pointer"
                  />
                  <input
                    type="number"
                    min="10"
                    max="600"
                    value={postRoll}
                    onChange={(e) => setPostRoll(Math.max(10, Number(e.target.value)))}
                    className="w-16 bg-[#161616] border border-neutral-700 px-2 py-1 text-white text-center"
                  />
                </div>
              </div>

              {/* Total Calculation Display */}
              <div className="p-2.5 bg-[#141414] border border-neutral-800 flex items-center justify-between text-[11px]">
                <span className="text-neutral-400">Total New Snippet Duration:</span>
                <span className="text-white font-semibold font-mono">
                  {preRoll + postRoll} seconds ({(preRoll + postRoll) / 60 >= 1 ? `${((preRoll + postRoll) / 60).toFixed(1)} min` : ''})
                </span>
              </div>

              {expandError && (
                <div className="p-2.5 bg-red-950/40 border border-red-800 text-red-300 text-xs">
                  {expandError}
                </div>
              )}

              {expandSuccess && (
                <div className="p-2.5 bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-xs">
                  {expandSuccess}
                </div>
              )}

              {/* Action Buttons */}
              <div className="pt-3 border-t border-neutral-800 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setExpandSnippet(null)}
                  disabled={isExpanding}
                  className="px-3 py-1.5 border border-neutral-700 hover:border-neutral-500 text-neutral-300 hover:text-white transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isExpanding}
                  className="px-4 py-1.5 bg-neutral-100 text-black hover:bg-white font-semibold flex items-center gap-2 transition-colors disabled:opacity-50"
                >
                  {isExpanding ? (
                    <>
                      <RotateCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Re-clipping & Transcribing...</span>
                    </>
                  ) : (
                    <>
                      <Sliders className="w-3.5 h-3.5" />
                      <span>Update & Replace Snippet</span>
                    </>
                  )}
                </button>
              </div>
            </form>

          </div>
        </div>
      )}

    </div>
  );
};
