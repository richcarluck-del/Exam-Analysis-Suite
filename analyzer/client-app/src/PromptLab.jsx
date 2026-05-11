
import React, { useState, useEffect, useRef } from 'react';

const API_BASE_URL = 'http://127.0.0.1:5000';

function PromptLab() {
  // Configuration State
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [promptLabs, setPromptLabs] = useState([]);
  
  // Form Input State
  const [selectedProvider, setSelectedProvider] = useState('dashscope');
  const [selectedModel, setSelectedModel] = useState('qwen3.5-plus');
  const [selectedPromptLab, setSelectedPromptLab] = useState(null);
  const [promptContent, setPromptContent] = useState('');
  const [inputData, setInputData] = useState('D:\\10739\\Exam-Analysis-RAG\\data\\input');
  
  // Image optimization settings
  const [enableOptimization, setEnableOptimization] = useState(true); // Default enabled
  
  // Test State
  const [testId, setTestId] = useState(null);
  const [testStatus, setTestStatus] = useState('');
  const [testOutput, setTestOutput] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  
  // New Prompt Form State
  const [showNewPromptForm, setShowNewPromptForm] = useState(false);
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptContent, setNewPromptContent] = useState('');
  const [newPromptDescription, setNewPromptDescription] = useState('');
  const [newPromptTags, setNewPromptTags] = useState('');

  const pollingRef = useRef(null);

  // Fetch providers on mount
  useEffect(() => {
    console.log('[PromptLab] 开始加载数据...');
    
    // 加载供应商
    fetch(`${API_BASE_URL}/api/providers`)
      .then(res => {
        console.log('[PromptLab] Providers 响应状态:', res.status);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        console.log('[PromptLab] Providers 数据:', data);
        if (data && data.length > 0) {
          setProviders(data);
          // 如果没有选中供应商，设置默认值
          if (!selectedProvider && data.length > 0) {
            const defaultProvider = data.find(p => p.provider_name === 'dashscope') || data[0];
            setSelectedProvider(defaultProvider.provider_name);
          }
        } else {
          console.warn('[PromptLab] Providers 数据为空');
        }
      })
      .catch(err => {
        console.error('[PromptLab] 加载 Providers 失败:', err);
      });
    
    fetchPromptLabs();
  }, []);

  // Fetch models when provider changes
  useEffect(() => {
    if (!selectedProvider) {
      console.log('[PromptLab] 没有选中的供应商，跳过加载模型');
      return;
    }
    
    console.log('[PromptLab] 加载模型，供应商:', selectedProvider);
    
    fetch(`${API_BASE_URL}/api/models/${selectedProvider}`)
      .then(res => {
        console.log('[PromptLab] Models 响应状态:', res.status);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        console.log('[PromptLab] Models 数据:', data);
        if (data && data.length > 0) {
          setModels(data);
          // 尝试选择 qwen3.5-plus，否则选择第一个
          const preferredModel = data.find(m => m.model_name === 'qwen3.5-plus');
          if (preferredModel) {
            setSelectedModel('qwen3.5-plus');
          } else {
            setSelectedModel(data[0].model_name);
          }
        } else {
          console.warn('[PromptLab] Models 数据为空');
          setModels([]);
        }
      })
      .catch(err => {
        console.error('[PromptLab] 加载 Models 失败:', err);
        setModels([]);
      });
  }, [selectedProvider]);

  // Fetch prompt labs
  const fetchPromptLabs = () => {
    console.log('[PromptLab] 加载提示词列表...');
    
    fetch(`${API_BASE_URL}/api/prompt_lab`)
      .then(res => {
        console.log('[PromptLab] 提示词响应状态:', res.status);
        return res.json();
      })
      .then(data => {
        console.log('[PromptLab] 提示词数据:', data);
        setPromptLabs(data);
        if (data.length > 0 && !selectedPromptLab) {
          handleSelectPromptLab(data[0]);
        }
      })
      .catch(err => {
        console.error('[PromptLab] 加载提示词失败:', err);
      });
  };

  // Handle prompt selection
  const handleSelectPromptLab = (prompt) => {
    setSelectedPromptLab(prompt);
    setPromptContent(prompt.content);
  };

  // Handle new prompt creation
  const handleCreatePrompt = () => {
    fetch(`${API_BASE_URL}/api/prompt_lab`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newPromptName,
        content: newPromptContent,
        description: newPromptDescription,
        tags: newPromptTags,
      }),
    })
      .then(res => {
        if (res.ok) {
          alert('提示词创建成功！');
          setShowNewPromptForm(false);
          setNewPromptName('');
          setNewPromptContent('');
          setNewPromptDescription('');
          setNewPromptTags('');
          fetchPromptLabs();
        } else {
          return res.json().then(err => { throw new Error(err.error); });
        }
      })
      .catch(err => alert(`创建失败：${err.message}`));
  };

  // Handle delete prompt
  const handleDeletePrompt = (id) => {
    if (confirm('确定要删除这个提示词吗？')) {
      fetch(`${API_BASE_URL}/api/prompt_lab/${id}`, { method: 'DELETE' })
        .then(res => {
          if (res.ok) {
            alert('删除成功！');
            fetchPromptLabs();
          } else {
            alert('删除失败');
          }
        })
        .catch(console.error);
    }
  };

  // Handle test run
  const handleRunTest = () => {
    if (!selectedPromptLab) {
      alert('请先选择一个提示词');
      return;
    }
    
    if (!inputData || inputData.trim() === '') {
      alert('请输入数据路径或文本内容（必填）');
      return;
    }

    setIsRunning(true);
    setTestStatus('starting');
    setTestOutput('');
    setTestId(null);

    fetch(`${API_BASE_URL}/api/prompt_lab_test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt_lab_id: selectedPromptLab.id,
        provider_name: selectedProvider,
        model_name: selectedModel,
        input_data: inputData,
        enable_optimization: enableOptimization,  // 传递优化配置
      }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.test_id) {
          setTestId(data.test_id);
          startPolling(data.test_id);
        } else {
          alert(`测试启动失败：${data.error}`);
          setIsRunning(false);
        }
      })
      .catch(err => {
        alert(`测试启动失败：${err.message}`);
        setIsRunning(false);
      });
  };

  // Polling for test results
  const startPolling = (id) => {
    pollingRef.current = setInterval(() => {
      fetch(`${API_BASE_URL}/api/prompt_lab_test/${id}`)
        .then(res => res.json())
        .then(data => {
          setTestStatus(data.status);
          
          if (data.output_data) {
            setTestOutput(data.output_data);
          }
          
          if (data.status === 'success' || data.status === 'failed') {
            stopPolling();
            setIsRunning(false);
          }
        })
        .catch(console.error);
    }, 2000);
  };

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow">
        <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-bold text-gray-900">🧪 实验区</h1>
          <p className="mt-2 text-sm text-gray-600">
            在这里测试不同的提示词和模型组合，快速验证效果
          </p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Left Panel - Configuration */}
          <div className="lg:col-span-1 space-y-6">
            
            {/* API Configuration */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">⚙️ API 配置</h2>
              
              {/* Provider */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  API 供应商
                </label>
                <select
                  value={selectedProvider}
                  onChange={e => setSelectedProvider(e.target.value)}
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                >
                  {providers.map(p => (
                    <option key={p.provider_name} value={p.provider_name}>
                      {p.provider_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Model */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  模型名称
                </label>
                <select
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                >
                  {models.map(m => (
                    <option key={m.model_name} value={m.model_name}>
                      {m.model_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Input Data */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  输入数据 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={inputData}
                  onChange={e => setInputData(e.target.value)}
                  placeholder="图片路径或文本输入（必填）"
                  className="w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              {/* Image Optimization */}
              <div className="mb-4 p-3 bg-blue-50 rounded-md border border-blue-200">
                <div className="flex items-center mb-2">
                  <input
                    type="checkbox"
                    id="enable-optimization"
                    checked={enableOptimization}
                    onChange={e => setEnableOptimization(e.target.checked)}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="enable-optimization" className="ml-2 block text-sm font-medium text-gray-700">
                    📸 启用图片优化（节省 Token）
                  </label>
                </div>
                {enableOptimization && (
                  <div className="text-xs text-gray-600 ml-6">
                    <p>✅ 智能降采样：自动调整分辨率至 2048px</p>
                    <p>✅ 高质量压缩：保持文字清晰度</p>
                    <p>✅ 预计节省：20-30% Token</p>
                  </div>
                )}
              </div>
            </div>

            {/* Prompt List */}
            <div className="bg-white shadow rounded-lg p-6">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-medium text-gray-900">📝 提示词列表</h2>
                <button
                  onClick={() => setShowNewPromptForm(!showNewPromptForm)}
                  className="text-sm text-blue-600 hover:text-blue-800"
                >
                  {showNewPromptForm ? '取消' : '+ 新建'}
                </button>
              </div>

              {showNewPromptForm && (
                <div className="mb-4 p-4 bg-gray-50 rounded-md">
                  <input
                    type="text"
                    value={newPromptName}
                    onChange={e => setNewPromptName(e.target.value)}
                    placeholder="提示词名称"
                    className="w-full mb-2 border-gray-300 rounded-md text-sm"
                  />
                  <textarea
                    value={newPromptContent}
                    onChange={e => setNewPromptContent(e.target.value)}
                    placeholder="提示词内容"
                    rows={3}
                    className="w-full mb-2 border-gray-300 rounded-md text-sm"
                  />
                  <input
                    type="text"
                    value={newPromptDescription}
                    onChange={e => setNewPromptDescription(e.target.value)}
                    placeholder="描述（可选）"
                    className="w-full mb-2 border-gray-300 rounded-md text-sm"
                  />
                  <input
                    type="text"
                    value={newPromptTags}
                    onChange={e => setNewPromptTags(e.target.value)}
                    placeholder="标签（逗号分隔，可选）"
                    className="w-full mb-2 border-gray-300 rounded-md text-sm"
                  />
                  <button
                    onClick={handleCreatePrompt}
                    className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700"
                  >
                    创建提示词
                  </button>
                </div>
              )}

              <div className="space-y-2 max-h-64 overflow-y-auto">
                {promptLabs.map(p => (
                  <div
                    key={p.id}
                    className={`p-3 rounded-md cursor-pointer border ${
                      selectedPromptLab?.id === p.id
                        ? 'border-blue-500 bg-blue-50'
                        : 'border-gray-200 hover:bg-gray-50'
                    }`}
                    onClick={() => handleSelectPromptLab(p)}
                  >
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="font-medium text-sm">{p.name}</div>
                        {p.description && (
                          <div className="text-xs text-gray-500 truncate">{p.description}</div>
                        )}
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeletePrompt(p.id);
                        }}
                        className="text-red-600 hover:text-red-800 text-sm"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Run Test Button */}
            <button
              onClick={handleRunTest}
              disabled={isRunning || !selectedPromptLab}
              className={`w-full py-3 px-4 rounded-md font-medium text-white ${
                isRunning || !selectedPromptLab
                  ? 'bg-gray-400 cursor-not-allowed'
                  : 'bg-green-600 hover:bg-green-700'
              }`}
            >
              {isRunning ? '测试运行中...' : '▶️ 运行测试'}
            </button>
          </div>

          {/* Right Panel - Prompt Content & Results */}
          <div className="lg:col-span-2 space-y-6">
            
            {/* Prompt Content */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">📄 提示词全文</h2>
              {promptContent ? (
                <div className="prose max-w-none">
                  <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-4 rounded-md border">
                    {promptContent}
                  </pre>
                </div>
              ) : (
                <div className="text-gray-500 text-sm">请选择一个提示词查看内容</div>
              )}
            </div>

            {/* Test Results */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">🔬 测试结果</h2>
              
              {testStatus && (
                <div className="mb-4">
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                    testStatus === 'success' ? 'bg-green-100 text-green-800' :
                    testStatus === 'failed' ? 'bg-red-100 text-red-800' :
                    testStatus === 'running' ? 'bg-blue-100 text-blue-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {testStatus === 'running' && (
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-blue-800" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                      </svg>
                    )}
                    {testStatus === 'success' ? '✅ 成功' :
                     testStatus === 'failed' ? '❌ 失败' :
                     testStatus === 'running' ? '🔄 运行中' :
                     testStatus}
                  </span>
                </div>
              )}

              {testOutput ? (
                <div className="prose max-w-none">
                  <pre className="whitespace-pre-wrap text-sm bg-gray-50 p-4 rounded-md border">
                    {testOutput}
                  </pre>
                </div>
              ) : (
                <div className="text-gray-500 text-sm">
                  {isRunning ? '等待测试结果...' : '点击"运行测试"开始测试'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PromptLab;
