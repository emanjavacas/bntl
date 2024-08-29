
const { div, li, ul, span, button, h5, form, input, p, small, br } = van.tags;

$(document).ready(function(){

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
                case STATUS.UNKNOWNERROR: case STATUS.UNKNOWNFORMAT: case STATUS.EMPTYFILE:
                    statusClass = 'bg-danger'
            }
            const listItem = li({ class: 'list-group-item' },
                // truncate it
                span(file.filename),
                file.status.val == STATUS.DONE ? 
                    // download button enabled
                    button({ id: `btn-${file.sessionId}`, 
                        class: "btn btn-sm btn-primary float-end",
                        onclick: () => downloadFile(file.sessionId) }, "Download") :
                    // download button disabled
                    button({ id: `btn-${file.sessionId}`, class: "btn btn-sm btn-primary float-end disabled" }, "Download"),
                div(span({ id: `status-${file.sessionId}`, class: `badge ${statusClass}` }, file.status.val),
                // uploading status
                file.status.val == STATUS.UPLOADING ? span({ style: "margin: 1em 0 0 0", class: "badge text-bg-secondary" }, `${file.uploadChunk.val}/100`): span()))
            return listItem
        }

        return div({ class: "card" }, 
            div({ class: "card-header" }, "Indexing service"),
            div({ class: "card-body" },
                h5({ class: "card-title" }, "File Upload"),
                p({ class: "card-text" }, "Upload a RIS file from zotero"),
                form({ class: "input-group", id:"uploadForm" },
                    input({ type: "file", class: "form-control", id: "fileInput", multiple: true }),
                    button({ class: "btn btn-outline-secondary", type: "submit" }, "Upload"))),
            div(ul({ class: "list-group list-group-flush scroll", id: "fileList" },
                () => div(filelist.val.files.map(createListItem)))))
    }

    van.add($("#entryPoint"), Card());
});