export interface AbsCredentials {
  serverUrl: string;
  authMode: 'token' | 'userpass';
  token?: string;
  username?: string;
  password?: string;
}

export interface EncryptedVault {
  ciphertext: ArrayBuffer;
  iv: Uint8Array;
  isEncrypted: boolean;
}

export interface AbsUser {
  id: string;
  username: string;
  type?: string;
}

export interface AbsBookmark {
  id?: string;
  title: string;
  time: number;
  createdAt?: number;
}

export interface AbsActiveSession {
  libraryItemId: string;
  episodeId?: string | null;
  bookTitle: string;
  subtitle?: string;
  author: string;
  chapterName: string;
  currentTime: number;
  audioFilePath: string;
  duration?: number;
  coverPath?: string;
  bookmarks?: AbsBookmark[];
}

export interface Snippet {
  id: string;
  bookTitle: string;
  subtitle?: string;
  author: string;
  chapterName: string;
  timestamp: string;
  startTime: number;
  currentTime?: number;
  duration: number;
  audioUrl: string;
  transcript: string;
  markdownContent: string;
  createdAt: number;
  userId?: string;
  username?: string;
  libraryItemId?: string;
}

export interface StoredCredentials {
  serverUrl: string;
  sidecarUrl?: string;
  useProxy?: boolean;
  authMode: 'token' | 'userpass';
  token?: string;
  username?: string;
  password?: string;
  remember: boolean;
}
