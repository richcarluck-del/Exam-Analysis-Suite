import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import LoginPage from './LoginPage';
import AdminPage from './AdminPage';
import ChatPage from './ChatPage';
import ParentReportPage from './ParentReportPage';
import QuestionPaperPreviewPage from './QuestionPaperPreviewPage';
import TeacherReportPage from './TeacherReportPage';
import GovernanceReportPage from './GovernanceReportPage';
import MatchesPage from './MatchesPage';


function Nav() {
  return (
    <nav className="bg-gray-800 p-4">
      <ul className="flex space-x-4">
        <li><Link to="/admin" className="text-white hover:text-gray-300">管理</Link></li>
        <li><Link to="/chat" className="text-white hover:text-gray-300">问答</Link></li>
        <li><Link to="/report" className="text-white hover:text-gray-300">家长报告</Link></li>
        <li><Link to="/teacher-report" className="text-white hover:text-gray-300">教师诊断台</Link></li>
        <li><Link to="/governance-report" className="text-white hover:text-gray-300">治理台</Link></li>
        <li><Link to="/matches" className="text-white hover:text-gray-300">锚点匹配</Link></li>
        <li><Link to="/paper-preview" className="text-white hover:text-gray-300">试卷预览</Link></li>

      </ul>
    </nav>
  );
}

function App() {
  return (
    <Router>
      <Nav />
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/report" element={<ParentReportPage />} />
        <Route path="/teacher-report" element={<TeacherReportPage />} />
        <Route path="/governance-report" element={<GovernanceReportPage />} />
        <Route path="/matches" element={<MatchesPage />} />
        <Route path="/paper-preview" element={<QuestionPaperPreviewPage />} />

      </Routes>
    </Router>
  );
}

export default App;
