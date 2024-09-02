
const { div, li, ul, span, button, h5, form, input, p, small, br } = van.tags;

$(document).ready(function(){
    
    // state
    const filelist = van.state(new FileList([]));

    function addFileToList(filename, fileId, status, progress=0) {
        filelist.val = filelist.val.add(filename, fileId, status, progress);
    }

    function updateFileStatus(fileId, status, progress) {
        filelist.val = filelist.val.updateStatus(fileId, status, progress);
    }

    // file upload logic
    function uploadFileInChunks(file, fileId) {
        const chunkSize = 1 * 1024 * 1024; // 1MB
        const totalChunks = Math.ceil(file.size / chunkSize);
        let currentChunk = 0;

        function _readAndUploadNextChunk() {
            const start = currentChunk * chunkSize;
            const end = Math.min(start + chunkSize, file.size);
            const blob = file.slice(start, end);

            const reader = new FileReader();
            reader.onload = function (e) {
                const formData = new FormData();
                formData.append('file', new Blob([e.target.result], { type: file.type }), file.name);
                formData.append('chunk', currentChunk);
                formData.append('total_chunks', totalChunks);
                formData.append('file_id', fileId);
                $.ajax({
                    url: '/upload-file',
                    type: 'POST',
                    data: formData,
                    processData: false,
                    contentType: false,
                    success: function () {
                        console.log(`Chunk ${currentChunk}/${totalChunks} of ${file.name} - ${fileId} uploaded`);
                        if (currentChunk === totalChunks - 1) {
                            updateFileStatus(fileId, STATUS.INDEXING, 0);
                            checkStatus(fileId);
                        } else {
                            currentChunk++;
                            _readAndUploadNextChunk();
                            updateFileStatus(fileId, STATUS.UPLOADING, (currentChunk + 1) / totalChunks);
                        }
                    },
                    error: function (xhr, status, error) {
                        console.error(`Error uploading chunk ${currentChunk} of ${file.name}: ${error}`);
                        updateFileStatus(fileId, STATUS.UNKNOWNERROR);
                    }
                });
            }
            reader.onerror = function () {
                console.error(`Error reading chunk ${currentChunk} of ${file.name}`);
            }
            reader.readAsArrayBuffer(blob);
        } 
        _readAndUploadNextChunk();
    }

    function onSubmit(e) {
        e.preventDefault();
        var files = $('#fileInput')[0].files;
        if (files.length > 0) {
            for (let i = 0; i < files.length; i++) {
                const fileId = uuidv4();
                addFileToList(files[i].name, fileId, STATUS.UPLOADING, 0);
                // upload the file
                uploadFileInChunks(files[i], fileId);
            }
        }
        $('#fileInput').val('');
    }

    function isStatusDone(status) {
        return (
            status === STATUS.DONE ||
            status === STATUS.UNKNOWNERROR ||
            status === STATUS.UNKNOWNFORMAT ||
            status === STATUS.VECTORIZINGERROR ||
            status === STATUS.EMPTYFILE)
    }

    function checkStatus(fileId) {
        var interval = setInterval(function() {
            $.ajax({
                url: `/check-upload-status/${fileId}`,
                type: 'GET',
                success: function(response) {
                    updateFileStatus(fileId, response.current_status.status, response.current_status.progress);
                    if (isStatusDone(response.current_status.status)) {
                        clearInterval(interval);
                    }
                },
                error: function() {
                    // set error
                    updateFileStatus(fileId, STATUS.UNKNOWNERROR);
                    clearInterval(interval);
                }
            });
        }, 2000);
    }

    // layout
    function Card() {
        function createListItem(file) {
            var statusClass = 'bg-warning text-dark';
            switch (file.status.val) {
                case STATUS.UPLOADING:
                    statusClass = 'bg-warning text-dark'; break;
                case STATUS.INDEXING: case STATUS.VECTORIZING:
                    statusClass = 'bg-info'; break;
                case STATUS.DONE:
                    statusClass = 'bg-success'; break;
                case STATUS.UNKNOWNERROR: case STATUS.UNKNOWNFORMAT: case STATUS.EMPTYFILE: case STATUS.VECTORIZINGERROR:
                    statusClass = 'bg-danger'
            }
            const listItem = li({ class: 'list-group-item' },
                div({ class: "container-fluid py-1 px-0"},
                    div({ class: "row" }, 
                        div({ class: "col-8" },
                            button({ class: "btn btn-light position-relative disabled" },
                                file.filename,
                                span({ style: "font-size:10px;", 
                                       class: `position-absolute top-100 start-100 translate-middle badge rounded-pill ${statusClass}` }, 
                                    file.status.val),
                                file.status.val == STATUS.UPLOADING || file.status.val == STATUS.INDEXING ? 
                                    span({ style: "font-size:8px", 
                                           class: "position-absolute top-0 start-100 translate-middle badge bg-secondary rounded-pill" }, 
                                        `${Math.round(file.progress.val * 100, 2)}/100`): 
                                    span())),
                        div({ class: "col-4" },
                            isStatusDone(file.status.val) ? 
                            // download button enabled
                            button({ id: `btn-${file.fileId}`, 
                                class: "btn btn-sm btn-primary float-end",
                                onclick: () => downloadLog(file.fileId) }, "Log") :
                            // download button disabled
                            button({ id: `btn-${file.file_id}`, class: "btn btn-sm btn-primary float-end disabled" }, "Log")))
                )
            )
            return listItem
        }

        return div({ class: "card" }, 
            div({ class: "card-header" }, "Indexing service"),
            div({ class: "card-body" },
                h5({ class: "card-title" }, "File Upload"),
                p({ class: "card-text" }, "Upload a RIS file from zotero"),
                form({ class: "input-group", id:"uploadForm", onsubmit: onSubmit },
                    input({ type: "file", class: "form-control", id: "fileInput", multiple: true }),
                    button({ class: "btn btn-outline-secondary", type: "submit" }, "Upload")),
                div(ul({ class: "list-group list-group-flush scroll", id: "fileList" },
                    () => div(filelist.val.files.map(createListItem))))))
    }

    van.add($("#entryPoint"), Card());
    // recall upload history
    $.ajax({
        url: "get-upload-history",
        type: 'GET',
        success: function(response) {
            $.each(response, function(index, item) {
                if (!isStatusDone(item.current_status.status)){ checkStatus(item.file_id); }
                addFileToList(item.filename, item.file_id, item.current_status.status, item.current_status.progress | 0);
            })
        },
        error: function() { }});
});


class FileList {
    constructor (files) { this.files = files }
    add (filename, fileId, status, progress=0) {
        this.files.unshift({ 
            filename: filename, 
            fileId: fileId,
            status: van.state(status), 
            progress: van.state(progress) });
        return new FileList(this.files);
    }
    updateStatus(fileId, status, progress) {
        const file = this.files.find(f => f.fileId === fileId);
        if (file) {
            // never downgrade from DONE
            if (file.status.val !== STATUS.DONE) {
                file.status = van.state(status);
                file.progress = van.state(progress);
            }
        }
        return new FileList(this.files);
    }
}


function downloadLog(fileId) {
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = `/get-upload-log?file_id=${fileId}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}


function uuidv4() {
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c =>
        (+c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> +c / 4).toString(16));
}