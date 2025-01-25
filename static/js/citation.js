// Import Citation.js directly from Skypack
import { Cite } from 'https://cdn.skypack.dev/@citation-js/core';
import 'https://cdn.skypack.dev/@citation-js/plugin-ris';
import 'https://cdn.skypack.dev/@citation-js/plugin-bibtex';
import 'https://cdn.skypack.dev/@citation-js/plugin-csl';

async function risToCitation(risText, outputFormat) {
    try {
        const citation = await Cite.async(risText);
        switch (outputFormat) {
            case "ris": return risText;
            case "bibtex": return citation.format('bibtex', {format: 'text'}).trim();
            case "modern-language-association": case "apa": return citation.format(
                "bibliography", {
                    format: "text",
                    template: outputFormat,
                    lang: 'en-US'}
                ).trim();
            default: console.log(`Unknown output format: ${outputFormat}`);
        } 
    } catch (error) {
        console.error('Error parsing RIS:', error);
        throw error;
    }
}

$(document).ready(() => {
    $(".citation-item").click(async function(e) {
        e.preventDefault();
        const documentId = $(this).data('document-id');
        const outputFormat = $(this).data('output-format');
        $.ajax({
            url: "exportRis",
            type: 'GET',
            data: {doc_id: documentId},
            success: async function(risText) {
                try {
                    const text = await risToCitation(risText, outputFormat);
                    const newTab = window.open();
                    if (newTab) {
                        newTab.document.write('<pre>' + text + '</pre>');
                    } else {
                        console.log("Couldn't open new tab");
                    }        
                } catch (error) {
                    console.log(`Error: ${error}, while processing RIS`);
                }
            },
            error: function (xhr, status, error) {
                console.log("Ajax error:", status, error);
            }
        });
    })
})