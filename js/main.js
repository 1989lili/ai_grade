// 评分标准各tab独立存储
const scoringStandards = {
    material: '',
    answer: '',
    example: '',
    requirement: ''
};
let currentContentTab = 'material';

// 桌面窗口控制（pywebview 原生窗口）
function setupWindowControls() {
    function bind(api) {
        document.querySelectorAll('.window-btn.minimize').forEach(btn => {
            btn.addEventListener('click', () => api.minimize());
        });
        document.querySelectorAll('.window-btn.close').forEach(btn => {
            btn.addEventListener('click', () => api.close());
        });
    }

    // pywebview 就绪事件
    window.addEventListener('pywebviewready', function () {
        if (window.pywebview && window.pywebview.api) {
            bind(window.pywebview.api);
        }
    });

    // 兜底：事件可能已触发，轮询检查
    var tries = 0;
    var timer = setInterval(function () {
        if (window.pywebview && window.pywebview.api) {
            bind(window.pywebview.api);
            clearInterval(timer);
        }
        if (++tries > 30) clearInterval(timer);
    }, 200);
}

// 等待DOM加载完成后执行
document.addEventListener('DOMContentLoaded', function() {
    setupWindowControls();

    // 窗口拖拽功能
    (function setupDrag() {
        var header = document.querySelector('.header');
        if (!header) return;

        var isDragging = false;
        var prevScreenX, prevScreenY;

        function getApi() {
            return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
        }

        header.addEventListener('mousedown', function(e) {
            if (e.target.closest('.window-btn')) return;
            isDragging = true;
            prevScreenX = e.screenX;
            prevScreenY = e.screenY;
            e.preventDefault();
        });

        window.addEventListener('mousemove', function(e) {
            if (!isDragging) return;
            var api = getApi();
            if (!api) return;
            var dx = e.screenX - prevScreenX;
            var dy = e.screenY - prevScreenY;
            prevScreenX = e.screenX;
            prevScreenY = e.screenY;
            api.move(dx, dy);
        });

        window.addEventListener('mouseup', function() {
            isDragging = false;
        });
    })();

    // 选项卡切换功能
    const tabs = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');

    // API Key显示/隐藏功能
    const eyeBtns = document.querySelectorAll('.eye-btn');
    eyeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.parentElement.querySelector('input');
            if (input) {
                if (input.type === 'password') {
                    input.type = 'text';
                    btn.textContent = '👁️‍🗨️';
                } else {
                    input.type = 'password';
                    btn.textContent = '👁️';
                }
            }
        });
    });

    // 服务商选择联动功能
    const providerSelect = document.querySelector('.provider-select');
    const apiUrlLink = document.querySelector('.api-url-link');
    const providerConfigs = document.querySelectorAll('.provider-config');

    // 每个 provider 的上次配置缓存（页面内记忆，切换时自动恢复）
    var providerMemory = {};

    function loadProviderMemory() {
        fetch('/api/get-presets')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'success' && data.presets.length > 0) {
                    data.presets.forEach(function(p) {
                        if (!providerMemory[p.provider] || p.timestamp > providerMemory[p.provider].timestamp) {
                            providerMemory[p.provider] = {
                                apiKey: p.apiKey || '',
                                modelName: p.modelName || ''
                            };
                        }
                    });
                }
            })
            .catch(function() {});
    }

    function applyProviderMemory(provider) {
        var mem = providerMemory[provider];
        if (!mem) return;
        var apiEl = document.getElementById('api-key-' + provider);
        var modelEl = document.getElementById('model-name-' + provider);
        if (apiEl && mem.apiKey) apiEl.value = mem.apiKey;
        if (modelEl && mem.modelName) modelEl.value = mem.modelName;
    }

    loadProviderMemory();

    if (providerSelect && apiUrlLink && providerConfigs.length > 0) {
        providerSelect.addEventListener('change', function() {
            const selectedProvider = this.value;

            // 切换配置区域
            providerConfigs.forEach(config => {
                if (config.dataset.provider === selectedProvider) {
                    config.style.display = 'block';
                } else {
                    config.style.display = 'none';
                }
            });

            // 自动恢复该 provider 的上次配置
            applyProviderMemory(selectedProvider);

            // 更新API Key申请地址
            if (selectedProvider === 'doubao') {
                apiUrlLink.href = 'https://console.volcengine.com/';
                apiUrlLink.textContent = 'https://console.volcengine.com/';
            } else if (selectedProvider === 'deepseek') {
                apiUrlLink.href = 'https://platform.deepseek.com/';
                apiUrlLink.textContent = 'https://platform.deepseek.com/';
            } else if (selectedProvider === 'zhipu') {
                apiUrlLink.href = 'https://open.bigmodel.cn/';
                apiUrlLink.textContent = 'https://open.bigmodel.cn/';
            }
        });
    }

    // 获取当前选中服务商的配置（视觉直评内置，直接用服务商配置一次调用识别+评分）
    function getCurrentProviderConfig() {
        const selectedProvider = document.querySelector('.provider-select').value;
        return {
            provider: selectedProvider,
            apiKey: document.getElementById(`api-key-${selectedProvider}`).value,
            modelName: document.getElementById(`model-name-${selectedProvider}`).value
        };
    }

    // 评分标准页面功能
    const scoringStandardTab = document.getElementById('scoring-standard-tab');
    if (scoringStandardTab) {
        // 清空功能
        const clearBtn = scoringStandardTab.querySelector('.clear-btn');
        const editorContent = scoringStandardTab.querySelector('.editor-content');
        
        if (clearBtn && editorContent) {
            clearBtn.addEventListener('click', () => {
                editorContent.innerHTML = '';
            });
        }
        
        // 复制功能
        const copyBtn = scoringStandardTab.querySelector('.copy-btn');
        if (copyBtn && editorContent) {
            copyBtn.addEventListener('click', () => {
                const text = editorContent.textContent;
                navigator.clipboard.writeText(text).then(() => {
                    // 可以添加复制成功的提示
                });
            });
        }
        
        // 页码切换功能
        const prevPageBtn = scoringStandardTab.querySelector('.prev-page');
        const nextPageBtn = scoringStandardTab.querySelector('.next-page');
        const pageNumber = scoringStandardTab.querySelector('.page-number');
        let currentPage = 1;
        
        if (prevPageBtn && nextPageBtn && pageNumber) {
            prevPageBtn.addEventListener('click', () => {
                if (currentPage > 1) {
                    currentPage--;
                    pageNumber.textContent = currentPage;
                    // 这里可以添加加载上一页预设的逻辑
                }
            });
            
            nextPageBtn.addEventListener('click', () => {
                if (currentPage < 10) {
                    currentPage++;
                    pageNumber.textContent = currentPage;
                    // 这里可以添加加载下一页预设的逻辑
                }
            });
        }
        
        // 字体大小调整功能
        const decreaseFontBtn = scoringStandardTab.querySelector('.decrease-font');
        const increaseFontBtn = scoringStandardTab.querySelector('.increase-font');
        let currentFontSize = 16;
        
        if (decreaseFontBtn && increaseFontBtn && editorContent) {
            decreaseFontBtn.addEventListener('click', () => {
                if (currentFontSize > 12) {
                    currentFontSize--;
                    editorContent.style.fontSize = `${currentFontSize}px`;
                }
            });
            
            increaseFontBtn.addEventListener('click', () => {
                if (currentFontSize < 24) {
                    currentFontSize++;
                    editorContent.style.fontSize = `${currentFontSize}px`;
                }
            });
        }
        
        // 文本格式切换功能
        const textFormatBtn = scoringStandardTab.querySelector('.text-format');
        const formulaFormatBtn = scoringStandardTab.querySelector('.formula-format');
        
        if (textFormatBtn && formulaFormatBtn && editorContent) {
            textFormatBtn.addEventListener('click', () => {
                textFormatBtn.classList.add('active');
                formulaFormatBtn.classList.remove('active');
                // 这里可以添加切换到纯文本格式的逻辑
            });
            
            formulaFormatBtn.addEventListener('click', () => {
                formulaFormatBtn.classList.add('active');
                textFormatBtn.classList.remove('active');
                // 这里可以添加切换到融合格式的逻辑
            });
        }
        
        // 内容标签切换功能（独立存储各tab内容）
        const contentTabs = scoringStandardTab.querySelectorAll('.content-tab');
        const scoringEditor = document.getElementById('scoring-editor');
        contentTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetTab = tab.dataset.tab;
                if (targetTab) {
                    // 保存当前tab内容
                    scoringStandards[currentContentTab] = scoringEditor.innerHTML;
                    // 切换到新tab
                    contentTabs.forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    currentContentTab = targetTab;
                    // 加载新tab内容
                    scoringEditor.innerHTML = scoringStandards[targetTab];
                }
            });
        });
        
        // 添加图片功能
        const addImageBtn = scoringStandardTab.querySelector('.add-image-btn');
        const imageUploadInput = scoringStandardTab.querySelector('#image-upload');
        
        if (addImageBtn && imageUploadInput) {
            // 点击添加图片按钮时触发文件选择
            addImageBtn.addEventListener('click', () => {
                imageUploadInput.click();
            });
            
            // 文件选择变化时处理图片上传
            imageUploadInput.addEventListener('change', function(e) {
                const file = e.target.files[0];
                if (file) {
                    // 检查文件类型
                    if (!file.type.startsWith('image/')) {
                        alert('请选择图片文件！');
                        return;
                    }
                    
                    // 检查文件大小（限制为5MB）
                    if (file.size > 5 * 1024 * 1024) {
                        alert('图片大小不能超过5MB！');
                        return;
                    }
                    
                    // 创建文件读取器
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        // 创建图片元素
                        const img = document.createElement('img');
                        img.src = e.target.result;
                        
                        // 创建图片容器
                        const imgContainer = document.createElement('div');
                        imgContainer.className = 'image-container';
                        
                        // 创建删除按钮
                        const deleteBtn = document.createElement('button');
                        deleteBtn.innerHTML = '×';
                        deleteBtn.className = 'image-delete-btn';
                        
                        // 删除图片功能
                        deleteBtn.addEventListener('click', (event) => {
                            event.stopPropagation();
                            imgContainer.remove();
                        });
                        
                        imgContainer.appendChild(img);
                        imgContainer.appendChild(deleteBtn);
                        
                        // 将图片插入到编辑区域
                        const editorContent = scoringStandardTab.querySelector('.editor-content');
                        editorContent.appendChild(imgContainer);
                        
                        // 清空文件输入，允许重复选择同一文件
                        imageUploadInput.value = '';
                        
                        // 显示成功提示
                        showImageUploadSuccess();
                    };
                    
                    reader.onerror = function() {
                        alert('图片读取失败，请重试！');
                    };
                    
                    reader.readAsDataURL(file);
                }
            });
        }
        
        // 显示图片上传成功提示
        function showImageUploadSuccess() {
            const successMsg = document.createElement('div');
            successMsg.textContent = '图片上传成功！';
            successMsg.style.position = 'fixed';
            successMsg.style.top = '20px';
            successMsg.style.right = '20px';
            successMsg.style.background = '#4CAF50';
            successMsg.style.color = 'white';
            successMsg.style.padding = '10px 20px';
            successMsg.style.borderRadius = '5px';
            successMsg.style.zIndex = '10000';
            successMsg.style.boxShadow = '0 2px 10px rgba(0,0,0,0.2)';
            successMsg.style.fontSize = '14px';
            successMsg.style.fontWeight = 'bold';
            
            document.body.appendChild(successMsg);
            
            // 3秒后自动消失
            setTimeout(() => {
                successMsg.style.opacity = '0';
                successMsg.style.transition = 'opacity 0.5s ease';
                setTimeout(() => {
                    if (successMsg.parentNode) {
                        successMsg.parentNode.removeChild(successMsg);
                    }
                }, 500);
            }, 3000);
        }

        // ---------- 评分标准模板：保存 / 快速选择（最近5次）/ 模板库管理 ----------
        const templateSelect = document.getElementById('scoring-template-select');
        const templateSaveBtn = document.getElementById('scoring-template-save');
        const templateOpenBtn = document.getElementById('scoring-template-open');
        const templateOverlay = document.getElementById('scoring-template-overlay');
        const templatePanelClose = document.getElementById('scoring-template-panel-close');
        const templatePanelList = document.getElementById('scoring-template-panel-list');
        // 服务端返回顺序：旧 → 新；界面展示倒序（新在前）
        let scoringTemplates = [];

        function showToast(text) {
            const msg = document.createElement('div');
            msg.textContent = text;
            msg.style.position = 'fixed';
            msg.style.top = '20px';
            msg.style.left = '50%';
            msg.style.transform = 'translateX(-50%)';
            msg.style.background = 'rgba(0,0,0,0.78)';
            msg.style.color = '#fff';
            msg.style.padding = '8px 16px';
            msg.style.borderRadius = '6px';
            msg.style.zIndex = '10001';
            msg.style.fontSize = '13px';
            document.body.appendChild(msg);
            setTimeout(function() {
                msg.style.opacity = '0';
                msg.style.transition = 'opacity 0.4s ease';
                setTimeout(function() {
                    if (msg.parentNode) msg.parentNode.removeChild(msg);
                }, 400);
            }, 1600);
        }

        function collectScoringStandards() {
            // 先同步当前正在编辑的 tab，保证四个 tab 内容都是最新
            if (scoringEditor) scoringStandards[currentContentTab] = scoringEditor.innerHTML;
            return {
                material: scoringStandards.material,
                answer: scoringStandards.answer,
                example: scoringStandards.example,
                requirement: scoringStandards.requirement
            };
        }

        function applyScoringStandards(s) {
            scoringStandards.material = s.material || '';
            scoringStandards.answer = s.answer || '';
            scoringStandards.example = s.example || '';
            scoringStandards.requirement = s.requirement || '';
            if (scoringEditor) scoringEditor.innerHTML = scoringStandards[currentContentTab];
        }

        function stripHtml(html) {
            const d = document.createElement('div');
            d.innerHTML = html || '';
            return (d.textContent || '').replace(/\s+/g, ' ').trim();
        }

        function fmtTemplateTime(iso) {
            if (!iso) return '';
            const d = new Date(iso);
            if (isNaN(d.getTime())) return '';
            const p = function(n) { return (n < 10 ? '0' : '') + n; };
            return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
        }

        function templateDisplayName(t) {
            return t.name || ('模板 ' + fmtTemplateTime(t.timestamp));
        }

        function loadTemplateFromIndex(fileIndex) {
            const t = scoringTemplates[fileIndex];
            if (!t) return;
            applyScoringStandards(t);
            showToast('已载入模板：' + templateDisplayName(t));
        }

        function renderTemplateSelect() {
            if (!templateSelect) return;
            if (scoringTemplates.length === 0) {
                templateSelect.innerHTML = '<option value="">暂无已保存的模板</option>';
                templateSelect.disabled = true;
                return;
            }
            templateSelect.disabled = false;
            // 默认只列最近5个（新 → 旧）
            const recent = scoringTemplates.slice(-5).reverse();
            templateSelect.innerHTML = '<option value="">— 选择模板（最近5次保存）—</option>';
            recent.forEach(function(t) {
                const opt = document.createElement('option');
                opt.value = String(scoringTemplates.indexOf(t));
                opt.textContent = templateDisplayName(t) + '　' + fmtTemplateTime(t.timestamp);
                templateSelect.appendChild(opt);
            });
            templateSelect.value = '';
        }

        function renderTemplatePanel() {
            if (!templatePanelList) return;
            templatePanelList.innerHTML = '';
            if (scoringTemplates.length === 0) {
                templatePanelList.innerHTML = '<div class="preset-panel-empty">暂无已保存的模板。<br>在"评分标准"填好内容后点"💾 保存"即可。</div>';
                return;
            }
            // 新 → 旧 展示，全部可见（弹窗内可滚动）
            for (let revIndex = 0; revIndex < scoringTemplates.length; revIndex++) {
                const fileIndex = scoringTemplates.length - 1 - revIndex;
                const t = scoringTemplates[fileIndex];

                const item = document.createElement('div');
                item.className = 'preset-panel-item template-panel-item';

                const info = document.createElement('div');
                info.className = 'preset-panel-item-info';

                const titleLine = document.createElement('div');
                const nameSpan = document.createElement('span');
                nameSpan.className = 'template-item-name';
                nameSpan.textContent = templateDisplayName(t);
                const dateSpan = document.createElement('span');
                dateSpan.className = 'template-item-date';
                dateSpan.textContent = fmtTemplateTime(t.timestamp);
                titleLine.appendChild(nameSpan);
                titleLine.appendChild(dateSpan);

                const preview = document.createElement('div');
                preview.className = 'template-item-preview';
                const mat = stripHtml(t.material);
                const ans = stripHtml(t.answer);
                const exa = stripHtml(t.example);
                const req = stripHtml(t.requirement);
                const parts = [];
                if (mat) parts.push('材料:' + mat.slice(0, 16));
                if (ans) parts.push('答案:' + ans.slice(0, 16));
                if (exa) parts.push('示例:' + exa.slice(0, 16));
                if (req) parts.push('要求:' + req.slice(0, 16));
                preview.textContent = parts.join(' | ') || '（空白内容）';

                info.appendChild(titleLine);
                info.appendChild(preview);
                item.appendChild(info);

                const delBtn = document.createElement('button');
                delBtn.className = 'preset-panel-item-delete';
                delBtn.innerHTML = '×';
                delBtn.title = '删除该模板';
                delBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    if (!confirm('确定删除模板「' + templateDisplayName(t) + '」吗？')) return;
                    fetch('/api/delete-scoring-template', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ index: fileIndex })
                    }).then(function(r) { return r.json(); })
                      .then(function(d) {
                          if (d.status === 'success') {
                              showToast('模板已删除');
                              refreshScoringTemplates();
                          } else {
                              showToast(d.message || '删除失败');
                          }
                      })
                      .catch(function() { showToast('删除失败，请稍后重试'); });
                });
                item.appendChild(delBtn);

                item.addEventListener('click', function() {
                    loadTemplateFromIndex(fileIndex);
                    closeTemplatePanel();
                });

                templatePanelList.appendChild(item);
            }
        }

        function refreshScoringTemplates() {
            return fetch('/api/get-scoring-templates')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    scoringTemplates = (data.status === 'success') ? (data.templates || []) : [];
                    renderTemplateSelect();
                    renderTemplatePanel();
                })
                .catch(function() {
                    scoringTemplates = [];
                    renderTemplateSelect();
                    renderTemplatePanel();
                });
        }

        function openTemplatePanel() {
            if (!templateOverlay) return;
            renderTemplatePanel();
            templateOverlay.classList.add('active');
        }

        function closeTemplatePanel() {
            if (templateOverlay) templateOverlay.classList.remove('active');
        }

        if (templateSaveBtn) {
            templateSaveBtn.addEventListener('click', function() {
                const standards = collectScoringStandards();
                if (!standards.material && !standards.answer && !standards.example && !standards.requirement) {
                    alert('当前评分标准内容为空，请先填写题目材料/参考答案等内容再保存。');
                    return;
                }
                const now = new Date();
                const p = function(n) { return (n < 10 ? '0' : '') + n; };
                const defaultName = '模板 ' + p(now.getMonth() + 1) + '-' + p(now.getDate()) + ' ' + p(now.getHours()) + ':' + p(now.getMinutes());
                const input = prompt('给模板起个简短名称（留空则按保存时间自动命名）：', defaultName);
                if (input === null) return; // 用户取消
                const name = input.trim();

                fetch('/api/save-scoring-template', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        material: standards.material,
                        answer: standards.answer,
                        example: standards.example,
                        requirement: standards.requirement
                    })
                }).then(function(r) { return r.json(); })
                  .then(function(d) {
                      if (d.status === 'success') {
                          showToast('已保存模板：' + (d.template && d.template.name ? d.template.name : name || '未命名'));
                          refreshScoringTemplates();
                      } else {
                          alert('保存失败：' + (d.message || '未知错误'));
                      }
                  })
                  .catch(function() { alert('保存失败，请稍后重试'); });
            });
        }

        if (templateSelect) {
            templateSelect.addEventListener('change', function() {
                const fileIndex = parseInt(templateSelect.value, 10);
                templateSelect.value = '';
                if (!isNaN(fileIndex) && scoringTemplates[fileIndex]) {
                    loadTemplateFromIndex(fileIndex);
                }
            });
        }

        if (templateOpenBtn) {
            templateOpenBtn.addEventListener('click', openTemplatePanel);
        }
        if (templatePanelClose) {
            templatePanelClose.addEventListener('click', closeTemplatePanel);
        }
        if (templateOverlay) {
            templateOverlay.addEventListener('click', function(e) {
                if (e.target === templateOverlay) closeTemplatePanel();
            });
        }

        // 进入页面时自动加载已保存的模板列表
        refreshScoringTemplates();
    }

    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => {
            // 移除所有选项卡的active类
            tabs.forEach(t => t.classList.remove('active'));
            // 添加当前选项卡的active类
            tab.classList.add('active');
            
            // 隐藏所有内容
            tabContents.forEach(content => content.classList.remove('active'));
            // 显示当前选项卡对应的内容
            tabContents[index].classList.add('active');
        });
    });

    // 箭头按钮功能
    const arrowBtns = document.querySelectorAll('.arrow-btn');
    arrowBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.closest('.setting-input').querySelector('input');
            const settingLabel = btn.closest('.setting-item').querySelector('.setting-label').textContent;
            let value = parseFloat(input.value);
            let step = 0.1;
            
            // 根据不同的设置项设置不同的步长
            if (['改卷数量', '已改数量', '题目满分', '打分个数'].includes(settingLabel)) {
                step = 1;
            } else if (settingLabel === '打分步长') {
                step = 0.5;
            }
            
            if (btn.textContent === '▲') {
                value += step;
            } else {
                value -= step;
            }
            
            // 确保值不为负数
            if (value < 0) {
                value = 0;
            }
            
            // 已改数量不能超过改卷数量
            if (settingLabel === '已改数量') {
                const totalInput = document.querySelector('.setting-group .setting-item:nth-child(1) input');
                if (totalInput) {
                    const total = parseFloat(totalInput.value) || 0;
                    if (value > total) {
                        value = total;
                    }
                }
            }
            
            // 根据步长决定小数位数
            if (step === 1) {
                input.value = Math.round(value);
            } else {
                input.value = value.toFixed(1);
            }
            
            updateProgress();
        });
    });

    // 更新进度条
    function updateProgress() {
        try {
            const totalInput = document.querySelector('.setting-group .setting-item:nth-child(1) input');
            const completedInput = document.querySelector('.setting-group .setting-item:nth-child(2) input');
            if (!totalInput || !completedInput) {
                return;
            }
            let total = parseFloat(totalInput.value) || 0;
            let completed = parseFloat(completedInput.value) || 0;
            
            // 已改数量不能超过改卷数量
            if (completed > total) {
                completed = total;
                completedInput.value = Math.round(completed);
            }
            
            const progress = total > 0 ? (completed / total) * 100 : 0;
            
            const progressFill = document.querySelector('.progress-fill');
            const progressText = document.querySelector('.progress-text');
            const footer = document.querySelector('.footer');
            const progressBar = document.querySelector('.progress-bar');
            
            if (progressFill && progressText) {
                progressFill.style.width = `${progress}%`;
                progressText.textContent = `${completed} / ${total}`;
            }
            
            // 检查任务是否完成
            const isCompleted = total > 0 && completed >= total;

            // 应用任务完成样式
            if (isCompleted) {
                if (footer) {
                    footer.classList.add('task-completed');
                }
                if (progressBar) {
                    progressBar.classList.add('task-completed');
                }
                if (progressFill) {
                    progressFill.classList.add('task-completed');
                }
            } else {
                // 移除任务完成样式
                if (footer) {
                    footer.classList.remove('task-completed');
                }
                if (progressBar) {
                    progressBar.classList.remove('task-completed');
                }
                if (progressFill) {
                    progressFill.classList.remove('task-completed');
                }
            }
        } catch (error) {
            console.error('Error updating progress:', error);
        }
    }

    // 为输入框添加事件监听器，确保直接修改值时也能更新进度条
    const inputFields = document.querySelectorAll('.setting-input input');
    inputFields.forEach(input => {
        input.addEventListener('input', updateProgress);
    });

    // 初始化进度条
    updateProgress();

    // 标记按钮 — 通过 Python API 控制外部 Win32 半透明蒙层
    const markingBtns = document.querySelectorAll('.marking-btn:not(.one-click-add)');
    const oneClickBtn = document.querySelector('.one-click-add');

    function api() {
        return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
    }

    function checkAllMarksStatus() {
        var allMarked = Array.from(markingBtns).every(function(btn) { return btn.textContent.trim() === '删除标记'; });
        if (oneClickBtn) {
            if (allMarked) {
                oneClickBtn.textContent = '一键删除';
                oneClickBtn.style.backgroundColor = '#dc3545';
            } else {
                oneClickBtn.textContent = '一键添加';
                oneClickBtn.style.backgroundColor = '#4CAF50';
            }
        }
    }

    // HTML 标记框功能
    (function setupHtmlMarkers() {
        var markerEls = {
            card: document.getElementById('marker-card'),
            score: document.getElementById('marker-score'),
            submit: document.getElementById('marker-submit')
        };

        function getApi() {
            return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
        }

        function notifyPython(mtype) {
            var api = getApi();
            if (!api) return;
            var el = markerEls[mtype];
            if (!el) return;
            var rect = el.getBoundingClientRect();
            api.update_marker(mtype, Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height));
        }

        // 为每个标记框设置拖拽
        Object.keys(markerEls).forEach(function(mtype) {
            var el = markerEls[mtype];
            if (!el) return;

            var dragState = null;

            el.addEventListener('mousedown', function(e) {
                if (e.target.classList.contains('html-marker-close')) return;
                var rect = el.getBoundingClientRect();
                dragState = {
                    startX: e.clientX,
                    startY: e.clientY,
                    startLeft: rect.left,
                    startTop: rect.top
                };
                e.preventDefault();
            });

            window.addEventListener('mousemove', function(e) {
                if (!dragState) return;
                el.style.left = (dragState.startLeft + e.clientX - dragState.startX) + 'px';
                el.style.top = (dragState.startTop + e.clientY - dragState.startY) + 'px';
            });

            window.addEventListener('mouseup', function() {
                if (!dragState) return;
                dragState = null;
                notifyPython(mtype);
            });

            // 关闭按钮
            var closeBtn = el.querySelector('.html-marker-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    window.hideMarkerByType(mtype);
                });
            }
        });

        // 显示标记（供按钮调用）
        window.showHtmlMarker = function(mtype) {
            var el = markerEls[mtype];
            if (!el) return;
            var w = el.offsetWidth || 300;
            var h = el.offsetHeight || 200;
            el.style.left = Math.max(0, (window.innerWidth - w) / 2) + 'px';
            el.style.top = Math.max(0, (window.innerHeight - h) / 3) + 'px';
            el.classList.add('active');
            notifyPython(mtype);
        };

        // 隐藏标记
        window.hideHtmlMarker = function(mtype) {
            var el = markerEls[mtype];
            if (el) el.classList.remove('active');
        };

        // 隐藏标记 + 更新按钮状态
        window.hideMarkerByType = function(mtype) {
            window.hideHtmlMarker(mtype);
            var api = getApi();
            if (api) api.hide_marker(mtype);
            var btnClass = mtype === 'card' ? 'card-area' : mtype === 'score' ? 'score-area' : 'submit-area';
            var btn = document.querySelector('.marking-btn.' + btnClass);
            if (btn && btn.textContent.trim() === '删除标记') {
                btn.textContent = '添加标记';
                var mi = btn.closest('.marking-item');
                var ml = mi.querySelector('.marking-label');
                ml.style.backgroundColor = 'rgba(233, 241, 254, 0.5)';
                ml.style.color = '';
                ml.style.fontWeight = '';
                ml.style.fontSize = '';
                ml.classList.remove('marked');
                checkAllMarksStatus();
            }
        };
    })();

    let gradingTimer = null;
    let gradingStartedAt = null;

    function formatElapsed(seconds) {
        var min = Math.floor(seconds / 60);
        var sec = seconds % 60;
        return String(min).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    }

    function setElapsedText(text) {
        var elapsed = document.getElementById('grading-elapsed');
        if (elapsed) elapsed.textContent = text;
    }

    function startElapsedTimer(prefix) {
        stopElapsedTimer();
        gradingStartedAt = Date.now();
        prefix = prefix || '用时 ';
        setElapsedText(prefix + '00:00');
        gradingTimer = setInterval(function() {
            var seconds = Math.floor((Date.now() - gradingStartedAt) / 1000);
            setElapsedText(prefix + formatElapsed(seconds));
        }, 1000);
    }

    function stopElapsedTimer() {
        if (gradingTimer) {
            clearInterval(gradingTimer);
            gradingTimer = null;
        }
    }

    function activateMainTab(tabId) {
        var target = document.getElementById(tabId);
        if (!target) return;
        tabContents.forEach(function(content, index) {
            var active = content === target;
            content.classList.toggle('active', active);
            if (tabs[index]) tabs[index].classList.toggle('active', active);
        });
    }

    async function readNdjsonStream(response, onEvent) {
        if (!response.ok) {
            throw new Error('流式接口请求失败，HTTP状态：' + response.status);
        }
        if (!response.body || !response.body.getReader) {
            throw new Error('当前环境不支持流式读取响应');
        }

        var reader = response.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var buffer = '';

        while (true) {
            var chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split('\n');
            buffer = lines.pop();
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line) continue;
                var event;
                try {
                    event = JSON.parse(line);
                } catch (error) {
                    throw new Error('解析流式响应失败：' + error.message);
                }
                await onEvent(event);
            }
        }

        buffer += decoder.decode();
        var finalLine = buffer.trim();
        if (finalLine) {
            var finalEvent;
            try {
                finalEvent = JSON.parse(finalLine);
            } catch (error) {
                throw new Error('解析流式响应失败：' + error.message);
            }
            await onEvent(finalEvent);
        }
    }

    function resetGradingUI() {
        stopElapsedTimer();
        setElapsedText('未开始');
        setStatusLine('');
        // 评分过程与结果已合并为同一个框，这里只需清空它
        var streamBox = document.getElementById('grading-stream-content');
        if (streamBox) {
            streamBox.textContent = '';
            streamBox.scrollTop = 0;
        }
    }

    function resetGradingProgress() {
        var completedInput = document.querySelector('.setting-group .setting-item:nth-child(2) input');
        if (completedInput) completedInput.value = 0;
        updateProgress();
        resetGradingUI();
    }

    function setStatusLine(text) {
        var line = document.getElementById('grading-status-line');
        if (line) line.textContent = text;
    }

    function appendStreamContent(text) {
        var box = document.getElementById('grading-stream-content');
        if (!box) return;
        // 用文本节点追加：textContent += 会把已插入的 HTML 段落压成纯文本，丢掉样式
        box.appendChild(document.createTextNode(text));
        box.scrollTop = box.scrollHeight;
    }

    // 批改失败也写进同一个“评分过程”框（结果框已合并、删除）
    function showGradingResult(result) {
        if (!result || result.status === 'success') return;
        var box = document.getElementById('grading-stream-content');
        if (!box) return;
        var wrap = document.createElement('div');
        wrap.className = 'stream-error';
        wrap.textContent = '【批改失败】' + (result.message || '批改失败');
        box.appendChild(wrap);
        box.scrollTop = box.scrollHeight;
    }

    // ── 两段式第一步：识别方式（AI配置页“识别方式”下拉） ──
    function getOcrSettings() {
        var sel = document.getElementById('ocr-mode-select');
        var mode = (sel && sel.value) || 'local';
        var settings = { ocrMode: mode, ocrApiKey: '' };
        if (mode === 'zhipu') {
            var keyEl = document.getElementById('ocr-zhipu-key');
            var zhipuKey = keyEl ? keyEl.value.trim() : '';
            if (!zhipuKey) {
                // 评分模型本身就选了智谱时，可直接复用智谱服务商的 Key
                var providerKey = document.getElementById('api-key-zhipu');
                zhipuKey = providerKey ? providerKey.value.trim() : '';
            }
            settings.ocrApiKey = zhipuKey;
        }
        return settings;
    }

    (function setupOcrModeSelect() {
        var sel = document.getElementById('ocr-mode-select');
        var keyItem = document.getElementById('ocr-zhipu-key-item');
        if (!sel) return;
        try {
            var saved = localStorage.getItem('ocr_mode');
            if (saved && Array.prototype.some.call(sel.options, function(o) { return o.value === saved; })) {
                sel.value = saved;
            }
        } catch (e) { /* localStorage 不可用时忽略 */ }
        function sync() {
            if (keyItem) keyItem.style.display = sel.value === 'zhipu' ? '' : 'none';
            try { localStorage.setItem('ocr_mode', sel.value); } catch (e) {}
        }
        sel.addEventListener('change', sync);
        sync();
    })();

    async function startGrading() {
        var debugInput = document.querySelector('.debug-info input');
        var progressFill = document.querySelector('.progress-fill');
        var progressText = document.querySelector('.progress-text');

        var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
        if (!api) { alert('API 未就绪，请稍候再试'); return; }

        // 恢复标记：逐个 await，后端 hide/show 已改为同步等待 tk 线程真正执行完，
        // 返回时标记窗口必然已重新显示，下一轮读取坐标才不会误判“标记丢失”
        async function restoreMarkers(cardArea, scoreBox, submitBtn) {
            await api.show_marker_at('card', cardArea.x, cardArea.y, cardArea.w, cardArea.h);
            await api.show_marker_at('score', scoreBox.x, scoreBox.y, scoreBox.w, scoreBox.h);
            await api.show_marker_at('submit', submitBtn.x, submitBtn.y, submitBtn.w, submitBtn.h);
        }

        // 检查标记
        var rects = await api.get_all_marker_rects();
        if (!rects || !rects.card || !rects.score || !rects.submit) {
            alert('请先完成所有标记设置（答题卡区域、打分框位置、提交按钮位置）');
            return;
        }

        // 保存评分标准
        var scoringEditor = document.getElementById('scoring-editor');
        if (scoringEditor) { scoringStandards[currentContentTab] = scoringEditor.innerHTML; }

        var config = getCurrentProviderConfig();
        if (!config.apiKey) { alert('请先在AI配置页面填写API Key'); return; }

        // 读取改卷参数
        var totalInput = document.querySelector('.setting-group .setting-item:nth-child(1) input');
        var completedInput = document.querySelector('.setting-group .setting-item:nth-child(2) input');
        var total = parseInt(totalInput.value) || 0;
        var completed = parseInt(completedInput.value) || 0;

        if (completed >= total) {
            alert('已改数量已达到改卷数量，无需继续批改');
            return;
        }

        setGradingButtons(true);

        var cardArea = rects.card;
        var scoreBox = rects.score;
        var submitBtn = rects.submit;

        debugInput.classList.remove('task-completed');
        progressFill.classList.remove('task-completed');
        updateProgress();

        // ── 循环批改，直到完成 ──
        while (true) {
            total = parseInt(totalInput.value) || 0;
            completed = parseInt(completedInput.value) || 0;
            if (completed >= total) {
                debugInput.value = '全部批改完成！共 ' + total + ' 份';
                debugInput.classList.add('task-completed');
                progressFill.classList.add('task-completed');
                updateProgress();
                break;
            }

            // 用户点击【停止】→ 阅完当前这一张后在这里停下来，不再开始下一张
            if (gradingStopRequested) {
                gradingStopRequested = false;
                debugInput.value = '已停止，本次共阅 ' + completed + ' 份';
                appendStreamContent('【已停止】完成 ' + completed + ' / ' + total + ' 份\n');
                updateProgress();
                break;
            }

            // 刷新标记位置（用户可能调整过）
            rects = await api.get_all_marker_rects();
            if (!rects || !rects.card || !rects.score || !rects.submit) {
                // 提示打印到“评分过程”面板（而不是只显示在进度条上）
                activateMainTab('scoring-process-tab');
                showGradingResult({ status: 'error', message: '标记丢失，已停止批改。请重新框定答题卡区域、打分框、提交按钮三个标记后再试。' });
                debugInput.value = '标记丢失，停止批改';
                break;
            }
            cardArea = rects.card;
            scoreBox = rects.score;
            submitBtn = rects.submit;
            var markersHidden = false;

            activateMainTab('scoring-process-tab');
            resetGradingUI();
            appendStreamContent('=== 第 ' + (completed + 1) + ' / ' + total + ' 份 ===\n');
            debugInput.value = '正在批改第 ' + (completed + 1) + ' 份...';
            startElapsedTimer('倒计时 ');

            // 启动扫描动画
            if (api.scan_card_area_loop) {
                api.scan_card_area_loop(cardArea.x, cardArea.y, cardArea.w, cardArea.h, 800);
            }

            // 隐藏标记
            if (api.hide_all_markers) {
                api.hide_all_markers();
                markersHidden = true;
                await new Promise(function(resolve) { setTimeout(resolve, 150); });
            }

            try {
                // ── 调AI评分（流式） ──
                var analyzeResult = null;
                var reasoningStarted = false;
                var analyzeTimings = {};
                var ocrSettings = getOcrSettings();
                var analyzeResponse = await fetch('/api/grade/analyze-stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cardArea: cardArea,
                        standards: scoringStandards,
                        provider: config.provider,
                        apiKey: config.apiKey,
                        modelName: config.modelName,
                        ocrMode: ocrSettings.ocrMode,
                        ocrApiKey: ocrSettings.ocrApiKey
                    })
                });

                await readNdjsonStream(analyzeResponse, async function(event) {
                    if (event.type === 'status') {
                        setStatusLine(event.message || '处理中...');
                        return;
                    }
                    if (event.type === 'reasoning') {
                        if (!reasoningStarted) {
                            setStatusLine('模型正在分析答题卡...');
                            reasoningStarted = true;
                        }
                        return;
                    }
                    if (event.type === 'token') {
                        // 模型现在按“纯文本标签行”分段输出，token 逐字上屏实现流式；
                        // 保险起见把代码块围栏 ``` ```json 剥掉
                        if (!reasoningStarted) {
                            setStatusLine('正在生成阅卷评析...');
                            reasoningStarted = true;
                        }
                        var chunk = String(event.content || '')
                            .replace(/```(?:json)?/gi, '')
                            .replace(/```/g, '');
                        if (chunk) {
                            appendStreamContent(chunk);
                        }
                        return;
                    }
                    if (event.type === 'ocr_text') {
                        // OCR 文本一次性到达，缓存到 timing 同名集合中，等 final 渲染
                        analyzeTimings.__ocr_text = event.text || '';
                        return;
                    }
                    if (event.type === 'ocr_text_chunk') {
                        // 识别文字统一在 final 后以【学生作答】整段呈现，这里不再逐行刷屏
                        setStatusLine('正在识别学生作答...');
                        return;
                    }
                    if (event.type === 'timing') {
                        // 后端埋点的耗时事件：capture / model_first_byte / model_call / parse
                        analyzeTimings[event.key] = event.duration_ms;
                        // 截图完成 → 扫描边框闪烁反馈"采集完成"
                        if (event.key === 'capture' && api && api.scan_flash) {
                            api.scan_flash(2);
                        }
                        return;
                    }
                    if (event.type === 'final') {
                        analyzeResult = event.result;
                        // OCR 文本兜底：若后端 final 缺 student_answer，使用流式 ocr_text 缓存
                        if (analyzeResult && !analyzeResult.student_answer && analyzeTimings.__ocr_text) {
                            analyzeResult.student_answer = analyzeTimings.__ocr_text;
                        }
                        // 合并本地累积的 timing 事件，兜底后端 final.timings 缺字段的情况
                        if (analyzeResult && !analyzeResult.timings) {
                            analyzeResult.timings = {};
                        }
                        if (analyzeResult && analyzeResult.timings) {
                            if (analyzeTimings.capture != null && analyzeResult.timings.capture_ms == null) {
                                analyzeResult.timings.capture_ms = analyzeTimings.capture;
                            }
                            if (analyzeTimings.ocr != null && analyzeResult.timings.ocr_ms == null) {
                                analyzeResult.timings.ocr_ms = analyzeTimings.ocr;
                            }
                            if (analyzeTimings.model_first_byte != null && analyzeResult.timings.model_first_byte_ms == null) {
                                analyzeResult.timings.model_first_byte_ms = analyzeTimings.model_first_byte;
                            }
                            if (analyzeTimings.model_call != null && analyzeResult.timings.model_ms == null) {
                                analyzeResult.timings.model_ms = analyzeTimings.model_call;
                            }
                            if (analyzeTimings.parse != null && analyzeResult.timings.parse_ms == null) {
                                analyzeResult.timings.parse_ms = analyzeTimings.parse;
                            }
                        }
                        return;
                    }
                    if (event.type === 'error') {
                        throw new Error(event.message || '评分失败');
                    }
                });

                if (!analyzeResult || analyzeResult.status !== 'success') {
                    throw new Error((analyzeResult && analyzeResult.message) || '评分失败');
                }

                if (api.hide_scan_line) api.hide_scan_line();
                // 模型文本已实时上屏（流式），这里补一行收尾提示
                appendStreamContent('\n');

                // ── 填写分数并提交 ──
                var applyResponse = await fetch('/api/grade/apply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        score: analyzeResult.score,
                        scoreBox: scoreBox,
                        submitBtn: submitBtn
                    })
                });
                var applyResult;
                try {
                    applyResult = await applyResponse.json();
                } catch (e) {
                    applyResult = { status: 'error', message: '服务器响应异常' };
                }
                if (applyResult.status !== 'success') {
                    throw new Error(applyResult.message || '填写分数或提交失败');
                }

                stopElapsedTimer();

                // ── 更新已改数量 ──
                completed = completed + 1;
                completedInput.value = completed;
                updateProgress();

                // 恢复标记（同步等 tk 线程真正显示完成，避免下一轮误判标记丢失）
                if (markersHidden && api && api.show_marker_at) {
                    await restoreMarkers(cardArea, scoreBox, submitBtn);
                    markersHidden = false;
                }

                debugInput.value = '第 ' + completed + '/' + total + ' 份完成，得分: ' + analyzeResult.score;

                if (completed >= total) {
                    debugInput.value = '全部批改完成！共 ' + total + ' 份';
                    debugInput.classList.add('task-completed');
                    progressFill.classList.add('task-completed');
                    updateProgress();
                    break;
                }

            } catch (error) {
                stopElapsedTimer();
                if (api.hide_scan_line) api.hide_scan_line();
                // 恢复标记（同步等 tk 线程真正显示完成）
                if (markersHidden && api && api.show_marker_at) {
                    await restoreMarkers(cardArea, scoreBox, submitBtn);
                }
                showGradingResult({ status: 'error', message: error.message });
                debugInput.value = '批改出错: ' + error.message;
                break;
            }
        }

        setGradingButtons(false);
    }

    var correctBtn = document.getElementById('correct-btn');
    var gradingActive = false;
    var gradingBusy = false;            // 同步防重入：避免双击连开两个批改循环
    var gradingStopRequested = false;   // 点击【停止】置真；阅完当前这一张后停止

    // 点击【停止】：只置标记，已发出的模型请求继续响应；批改循环阅完当前这一张
    // （含打分与提交）后，在开始下一张前发现标记即结束，按钮恢复【批改】。
    async function stopGrading() {
        if (gradingStopRequested) return;
        gradingStopRequested = true;
        if (correctBtn) {
            correctBtn.textContent = '停止中…';
            correctBtn.disabled = true;
        }
        appendStreamContent('【收到停止指令：阅完当前这一张后停止】\n');
    }

    function setGradingButtons(grading) {
        gradingActive = grading;
        if (correctBtn) {
            // 批改中按钮保持可点（文本为【停止】），用于中途暂停
            correctBtn.disabled = !grading;
            correctBtn.textContent = grading ? '停止' : '批改';
        }
    }

    if (correctBtn) {
        correctBtn.addEventListener('click', async function() {
            if (correctBtn.disabled || gradingBusy) return;
            if (gradingActive) {
                await stopGrading();       // 批改中：请求【停止】
                return;
            }
            gradingBusy = true;            // 同步占位，防双击重复启动
            setGradingButtons(true);       // 按钮立即变【停止】
            try {
                await startGrading();
            } finally {
                gradingBusy = false;
                setGradingButtons(false);  // 恢复【批改】
            }
        });
    }

    // 【重置】：把“已改数量”归零、清空评分过程，让【批改】可以重新开始
    var resetBtn = document.getElementById('reset-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function() {
            if (gradingActive || gradingBusy) return;   // 批改中不允许重置
            gradingStopRequested = false;
            var debugInput2 = document.querySelector('.debug-info input');
            if (debugInput2) {
                debugInput2.classList.remove('task-completed');
                debugInput2.value = '提示信息';
            }
            var progressFill2 = document.querySelector('.progress-fill');
            if (progressFill2) progressFill2.classList.remove('task-completed');
            var progressText2 = document.querySelector('.progress-text');
            if (progressText2) {
                var totalInput2 = document.querySelector('.setting-group .setting-item:nth-child(1) input');
                progressText2.textContent = '0 / ' + (parseInt(totalInput2 && totalInput2.value, 10) || 0);
            }
            resetGradingProgress();
        });
    }

    markingBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var mtype = this.classList.contains('card-area') ? 'card' : this.classList.contains('score-area') ? 'score' : 'submit';

            if (this.textContent.trim() === '添加标记') {
                var api2 = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
                if (!api2) { alert('API 未就绪，请稍候再试'); return; }
                // HTML 标记已禁用，使用 tkinter 桌面浮窗
                // showHtmlMarker(mtype);
                api2.show_marker(mtype);
                this.textContent = '删除标记';
                var mi = this.closest('.marking-item');
                var ml = mi.querySelector('.marking-label');
                if (this.classList.contains('card-area')) { ml.style.backgroundColor = 'rgba(229, 57, 53, 0.18)'; }
                else if (this.classList.contains('score-area')) { ml.style.backgroundColor = 'rgba(30, 136, 229, 0.18)'; }
                else if (this.classList.contains('submit-area')) { ml.style.backgroundColor = 'rgba(67, 160, 71, 0.18)'; }
                ml.style.color = '';
                ml.style.fontWeight = 'bold';
                ml.style.fontSize = '16px';
                ml.classList.add('marked');
            } else {
                var api2 = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
                if (api2) api2.hide_marker(mtype);
                // HTML 标记已禁用
                // window.hideHtmlMarker(mtype);
                this.textContent = '添加标记';
                var mi = this.closest('.marking-item');
                var ml = mi.querySelector('.marking-label');
                ml.style.backgroundColor = 'rgba(233, 241, 254, 0.5)';
                ml.style.color = '';
                ml.style.fontWeight = '';
                ml.style.fontSize = '';
                ml.classList.remove('marked');
            }
            checkAllMarksStatus();
        });
    });

    // 一键添加/删除
    if (oneClickBtn) {
        oneClickBtn.addEventListener('click', function() {
            if (this.textContent.trim() === '一键添加') {
                markingBtns.forEach(function(b) { if (b.textContent.trim() === '添加标记') b.click(); });
            } else {
                markingBtns.forEach(function(b) { if (b.textContent.trim() === '删除标记') b.click(); });
            }
        });
    }

    // 保存预设功能
    const savePresetBtn = document.querySelector('.save-preset-btn');
    if (savePresetBtn) {
        savePresetBtn.addEventListener('click', async () => {
            try {
                const config = getCurrentProviderConfig();
                
                if (!config.apiKey) {
                    alert('API Key不能为空！');
                    return;
                }
                
                const response = await fetch('/api/save-preset', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(config)
                });
                
                const data = await response.json();
                if (data.status === 'success') {
                    // 更新内存缓存，确保切换回来时能恢复
                    providerMemory[config.provider] = {
                        apiKey: config.apiKey,
                        modelName: config.modelName
                    };
                    alert('预设保存成功！');
                } else {
                    alert('预设保存失败：' + data.message);
                }
            } catch (error) {
                alert('保存预设时发生错误：' + error.message);
            }
        });
    }

    // 预设列表功能（弹窗面板）
    const presetListBtn = document.querySelector('.preset-list-btn');
    const presetOverlay = document.getElementById('preset-overlay');
    const presetPanelList = document.getElementById('preset-panel-list');
    const presetPanelClose = document.getElementById('preset-panel-close');

    function loadPresetToUI(preset) {
        const providerSelect = document.querySelector('.provider-select');
        const hasOption = Array.from(providerSelect.options).some(function(o) { return o.value === preset.provider; });
        if (!hasOption) {
            alert('该预设的服务商已不可用：' + preset.provider);
            return;
        }
        providerSelect.value = preset.provider;
        providerSelect.dispatchEvent(new Event('change'));

        var apiKeyEl = document.getElementById('api-key-' + preset.provider);
        var modelNameEl = document.getElementById('model-name-' + preset.provider);
        if (apiKeyEl) apiKeyEl.value = preset.apiKey || '';
        if (modelNameEl) modelNameEl.value = preset.modelName || '';
    }

    function renderPresetPanel(presets) {
        presetPanelList.innerHTML = '';
        if (!presets || presets.length === 0) {
            presetPanelList.innerHTML = '<div class="preset-panel-empty">暂无保存的预设</div>';
            return;
        }
        presets.slice().reverse().forEach(function(preset, i) {
            var item = document.createElement('div');
            item.className = 'preset-panel-item';

            var info = document.createElement('div');
            info.className = 'preset-panel-item-info';
            var providerLabel = preset.provider;
            info.innerHTML =
                '<span class="preset-panel-item-provider">' + providerLabel + '</span>' +
                '<span class="preset-panel-item-model">' + (preset.modelName || '(未设模型)') + '</span>' +
                '<div class="preset-panel-item-date">' + new Date(preset.timestamp).toLocaleString() + '</div>';

            var delBtn = document.createElement('button');
            delBtn.className = 'preset-panel-item-delete';
            delBtn.innerHTML = '×';
            delBtn.title = '删除此预设';
            delBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                if (confirm('确定删除该预设？')) {
                    fetch('/api/delete-preset', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ index: presets.length - 1 - i })
                    }).then(function(r) { return r.json(); })
                      .then(function(d) {
                          if (d.status === 'success') refreshPresetPanel();
                      });
                }
            });

            item.appendChild(info);
            item.appendChild(delBtn);
            item.addEventListener('click', function() {
                loadPresetToUI(preset);
                closePresetPanel();
            });
            presetPanelList.appendChild(item);
        });
    }

    function refreshPresetPanel() {
        fetch('/api/get-presets')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'success') {
                    renderPresetPanel(data.presets || []);
                }
            })
            .catch(function() {});
    }

    function openPresetPanel() {
        if (presetOverlay) {
            presetOverlay.classList.add('active');
            refreshPresetPanel();
        }
    }
    function closePresetPanel() {
        if (presetOverlay) presetOverlay.classList.remove('active');
    }

    if (presetListBtn) {
        presetListBtn.addEventListener('click', function() {
            if (presetOverlay && presetOverlay.classList.contains('active')) {
                closePresetPanel();
            } else {
                openPresetPanel();
            }
        });
    }
    if (presetPanelClose) {
        presetPanelClose.addEventListener('click', closePresetPanel);
    }
    if (presetOverlay) {
        presetOverlay.addEventListener('click', function(e) {
            if (e.target === presetOverlay) closePresetPanel();
        });
    }

    // 页面加载时自动加载最后保存的预设
    window.addEventListener('load', async () => {
        try {
            const response = await fetch('/api/get-last-preset');
            const data = await response.json();
            
            if (data.status === 'success' && data.preset && data.preset.provider) {
                // 加载最后保存的预设
                const preset = data.preset;
                
                // 切换服务商
                const providerSelect = document.querySelector('.provider-select');
                if (providerSelect) {
                    // 老预设的 provider 可能已下线；下拉里没有就跳过自动加载
                    const hasOption = Array.from(providerSelect.options).some(o => o.value === preset.provider);
                    if (!hasOption) return;
                    providerSelect.value = preset.provider;
                    
                    // 触发change事件以更新配置区域
                    const event = new Event('change');
                    providerSelect.dispatchEvent(event);
                    
                    // 填充配置
                    const apiKeyElement = document.getElementById(`api-key-${preset.provider}`);
                    const modelNameElement = document.getElementById(`model-name-${preset.provider}`);
                    if (apiKeyElement) {
                        apiKeyElement.value = preset.apiKey;
                    }
                    if (modelNameElement) {
                        modelNameElement.value = preset.modelName;
                    }
                }
            }
        } catch (error) {
            console.log('加载预设时发生错误：', error);
        }
    });

    // 初始化
});