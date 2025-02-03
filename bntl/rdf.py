
import rispy
import os
from glob import glob

from lxml import etree
from tqdm.auto import tqdm

from bntl import utils


namespaces = {
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'res': 'http://purl.org/vocab/resourcelist/schema#',
    'z': 'http://www.zotero.org/namespaces/export#',
    'ctag': 'http://commontag.org/ns#',
    'dcterms': 'http://purl.org/dc/terms/',
    'bibo': 'http://purl.org/ontology/bibo/',
    'foaf': 'http://xmlns.com/foaf/0.1/',
    'address': 'http://schemas.talis.com/2005/address/schema#'
}

def _parse_pages(pages_node):
    if pages_node is not None and pages_node.text:
        pages = pages_node.text.split('-')
        end_page = None
        if len(pages) == 2:
            start_page, end_page = pages
        else:
            start_page = pages[0]
        output = {"start_page": start_page}
        if end_page is not None:
            output["end_page"] = end_page
        return output

def _get_author_lookup(root):
    author_lookup = {}
    persons = root.findall('.//foaf:Person', namespaces=namespaces)

    for person in persons:
        node_id = person.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if not node_id:
            continue

        given_name = person.find('foaf:givenName', namespaces)
        surname = person.find('foaf:surname', namespaces)

        person_str = ''
        if surname is not None:
            person_str += surname.text
            if given_name is not None:
                person_str += ', ' + given_name.text
        
        author_lookup[node_id] = person_str
    
    return author_lookup

def _get_keyword_lookup(root):
    keyword_lookup = {}
    user_tags = root.findall('.//ctag:UserTag', namespaces)
    for user_tag in user_tags:
        node_id = user_tag.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if not node_id:
            continue
        label = user_tag.find('ctag:label', namespaces)
        if label is not None:
            keyword_lookup[node_id] = label.text.replace('(auteur)', '').strip()

    return keyword_lookup

def _parse_keywords(z_node, keyword_lookup):
    keywords = []
    tagged_elements = z_node.findall('.//ctag:tagged', namespaces=namespaces)
    for tagged in tagged_elements:
        node_id = tagged.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if node_id and node_id in keyword_lookup:
            keywords.append(keyword_lookup[node_id])

        user_tag = tagged.find('ctag:UserTag/ctag:label', namespaces=namespaces)
        if user_tag is not None:
            keywords.append(user_tag.text)

    return {'keywords': keywords}

## journal articles
def _parse_academic_article(article, author_lookup):
    bibo_info = {}

    # Authors
    authors = []
    author_list = article.find('.//rdf:Seq', namespaces=namespaces)
    if author_list is not None:
        for li in author_list.findall('rdf:li', namespaces=namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                authors.append(author_lookup[node_id])
    if authors:
        bibo_info['first_authors'] = authors

    # Basic metadata
    for node_name, field_key in [
        ('dcterms:title', 'title'),
        ('bibo:uri', 'urls'),
        ('dcterms:abstract', 'abstract'),
        ('bibo:doi', 'doi'),
        ('bibo:shortTitle', 'reviewed_item'),
        ('dcterms:source', 'notes_abstract')
    ]:
        node = article.find(node_name, namespaces)
        if node is not None and node.text:
            bibo_info[field_key] = node.text

    # Pages
    pages_node = article.find('bibo:pages', namespaces)
    if parsed_pages := _parse_pages(pages_node):
        for key, val in parsed_pages.items():
            bibo_info[key] = val

    # Reviews
    reviews_node = article.find('.//bibo:lccn', namespaces)
    if reviews_node is not None and reviews_node.text:
        bibo_info['research_notes'] = reviews_node.text

    # Issue information
    issue_node = article.find('.//bibo:Issue', namespaces=namespaces)
    if issue_node is not None:
        for node_name, field_key in [
            ('dcterms:date', 'year'),
            ('bibo:volume', 'volume'),
            ('bibo:issue', 'number')
        ]:
            node = issue_node.find(node_name, namespaces=namespaces)
            if node is not None and node.text:
                bibo_info[field_key] = node.text

    # Journal information
    journal_node = article.find('.//bibo:Journal', namespaces)
    if journal_node is not None:
        # Journal title
        journal_title_node = journal_node.find('dcterms:title', namespaces)
        if journal_title_node is not None and journal_title_node.text:
            bibo_info['journal_name'] = journal_title_node.text
        
        # ISSN
        issn_node = journal_node.find('bibo:issn', namespaces)
        if issn_node is not None and issn_node.text:
            if issn_node.text != 'nan':
                bibo_info['issn'] = issn_node.text

        # Look for Series within the Journal node
        series_nodes = journal_node.findall('.//bibo:Series', namespaces)
        if series_nodes:
            for series_node in series_nodes:
                if series_node is not None:
                    title_node = series_node.find('dcterms:title', namespaces)
                    if title_node is not None and title_node.text:
                        bibo_info['tertiary_title'] = title_node.text
                        break

    return bibo_info

def _parse_jour(z_node, author_lookup, keyword_lookup):
    info = {}
    
    # Try to find the academic article node
    bibo_node = None
    
    # First check direct child
    next_node = z_node.getnext()
    if next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}AcademicArticle':
        bibo_node = next_node
    
    # If not found, try resource reference
    if bibo_node is None:
        resource_url = z_node.xpath('.//res:resource/@rdf:resource', namespaces=namespaces)
        if resource_url:
            try:
                articles = z_node.xpath(f"//bibo:AcademicArticle", namespaces=namespaces)
                for article in articles:
                    if article.get('{'+namespaces['rdf']+'}about') == resource_url[0]:
                        bibo_node = article
                        break
            except:
                pass
    
    # If still not found, try direct search
    if bibo_node is None:
        articles = z_node.xpath('.//bibo:AcademicArticle', namespaces=namespaces)
        if articles:
            bibo_node = articles[0] if isinstance(articles, list) else articles
    
    # Only parse if we found a valid node
    if bibo_node is not None:
        info.update(_parse_academic_article(bibo_node, author_lookup))
    
    # Add keywords regardless
    info.update(_parse_keywords(z_node, keyword_lookup=keyword_lookup))
    return info

## books:
def _parse_bibo_book(book, author_lookup):
    bibo_info = {}

    authors = []
    author_list = book.find('.//bibo:authorList/rdf:Seq', namespaces)
    if author_list is not None:
        for li in author_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                authors.append(author_lookup[node_id])
    if authors:
        bibo_info['first_authors'] = authors

    editors = []
    editor_list = book.find('.//bibo:editorList/rdf:Seq', namespaces)
    if editor_list is not None:
        for li in editor_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                editors.append(author_lookup[node_id])
    if editors:
        bibo_info['secondary_authors'] = editors

    translators = []
    for translator_node in book.findall('.//bibo:translator', namespaces):
        node_id = translator_node.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if node_id in author_lookup:
            translators.append(author_lookup[node_id])
    if translators:
        bibo_info['tertiary_authors'] = translators

    source_node = book.find('dcterms:source', namespaces)
    if source_node is not None:
        bibo_info['notes_abstract'] = source_node.text

    edition_node = book.find('bibo:edition', namespaces)
    if edition_node is not None:
        bibo_info['edition'] = edition_node.text

    title_node = book.find('dcterms:title', namespaces)
    if title_node is not None:
        bibo_info['title'] = title_node.text

    date_node = book.find('dcterms:date', namespaces)
    if date_node is not None:
        bibo_info['year'] = date_node.text

    uri_node = book.find('bibo:uri', namespaces)
    if uri_node is not None:
        bibo_info['urls'] = uri_node.text
    
    abstract_node = book.find('dcterms:abstract', namespaces)
    if abstract_node is not None:
        bibo_info['abstract'] = abstract_node.text
    
    pages_node = book.find('bibo:numPages', namespaces)
    if parsed_pages := _parse_pages(pages_node):
        for key, val in parsed_pages.items():
            bibo_info[key] = val
    
    isbn_nodes = book.findall('bibo:isbn13', namespaces)
    if isbn_nodes is not None:
        bibo_info['issn'] = ' '.join([inode.text for inode in isbn_nodes])
    
    doi_node = book.find('bibo:doi', namespaces)
    if doi_node is not None:
        bibo_info['doi'] = doi_node.text

    reviews_node = book.find('.//bibo:lccn', namespaces)
    if reviews_node is not None:
        bibo_info['research_notes'] = reviews_node.text
    
    volume_node = book.find('bibo:volume', namespaces)
    if volume_node is not None:
        bibo_info['volume'] = volume_node.text

    reviewed_node = book.find('.//bibo:shortTitle', namespaces)
    if reviewed_node is not None:
        bibo_info['reviewed_item'] = reviewed_node.text

    series_node = book.find('.//bibo:Series', namespaces)
    if series_node is not None:
        series_title_node = series_node.find('dcterms:title', namespaces)
        if series_title_node is not None:
            bibo_info['secondary_title'] = series_title_node.text
        series_number_node = series_node.find('bibo:number', namespaces)
        if series_number_node is not None:
            bibo_info['series_volume'] = series_number_node.text

    publisher_node = book.find('{http://purl.org/dc/terms/}publisher/foaf:Organization', namespaces)
    if publisher_node is not None:
        publisher_name_node = publisher_node.find('{http://xmlns.com/foaf/0.1/}name', namespaces)
        locality_node = publisher_node.find('{http://schemas.talis.com/2005/address/schema#}localityName', namespaces)

        if publisher_name_node is not None:
            bibo_info['publisher'] = publisher_name_node.text
        if locality_node is not None:
            bibo_info['place_published'] = locality_node.text
   
    return bibo_info
    
def _parse_book(z_node, author_lookup, keyword_lookup):
    info = {}

    next_node = z_node.getnext()
    if next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Book':
        bibo_node = next_node
    else:
        resource_node = z_node.find('{http://purl.org/vocab/resourcelist/schema#}resource')
        if resource_node is not None:
            bibo_node = resource_node.find('{http://purl.org/ontology/bibo/}Book')
        else:
            bibo_node = z_node.find('{http://purl.org/ontology/bibo/}Book')
    
    if bibo_node is not None:
        info.update(_parse_bibo_book(bibo_node, author_lookup))
    
    info.update(_parse_keywords(z_node, keyword_lookup))
    return info

## chapters:
def _parse_bibo_chapter(chapter, author_lookup):
    bibo_info = {}

    authors = []
    author_list = chapter.find('.//bibo:authorList/rdf:Seq', namespaces=namespaces)
    if author_list is not None:
        for li in author_list.findall('rdf:li', namespaces=namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                authors.append(author_lookup[node_id])
    if authors:
        bibo_info['first_authors'] = authors

    editors = []
    editor_list = chapter.find('.//bibo:editorList/rdf:Seq', namespaces=namespaces)
    if editor_list is not None:
        for li in editor_list.findall('rdf:li', namespaces=namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                editors.append(author_lookup[node_id])
    if editors:
        bibo_info['secondary_authors'] = editors

    translators = []
    for translator_node in chapter.findall('.//bibo:translator', namespaces):
        node_id = translator_node.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if node_id in author_lookup:
            translators.append(author_lookup[node_id])
    if translators:
        bibo_info['tertiary_authors'] = translators

    source_node = chapter.find('dcterms:source', namespaces)
    if source_node is not None:
        bibo_info['notes_abstract'] = source_node.text

    title_node = chapter.find('dcterms:title', namespaces)
    if title_node is not None:
        bibo_info['title'] = title_node.text

    date_node = chapter.find('dcterms:date', namespaces)
    if date_node is not None:
        bibo_info['year'] = date_node.text

    uri_node = chapter.find('bibo:uri', namespaces)
    if uri_node is not None:
        bibo_info['urls'] = uri_node.text
    
    abstract_node = chapter.find('dcterms:abstract', namespaces)
    if abstract_node is not None:
        bibo_info['abstract'] = abstract_node.text

    reviews_node = chapter.find('.//bibo:lccn', namespaces)
    if reviews_node is not None:
        bibo_info['research_notes'] = reviews_node.text
    
    pages_node = chapter.find('bibo:pages', namespaces)
    if parsed_pages := _parse_pages(pages_node):
        for key, val in parsed_pages.items():
            bibo_info[key] = val
    
    isbn_nodes = chapter.findall('bibo:isbn13', namespaces)
    if isbn_nodes:
        bibo_info['issn'] = ' '.join([inode.text for inode in isbn_nodes])
    
    doi_node = chapter.find('bibo:doi', namespaces)
    if doi_node is not None:
        bibo_info['doi'] = doi_node.text

    volume_node = chapter.find('bibo:volume', namespaces)
    if volume_node is not None:
        bibo_info['volume'] = volume_node.text

    series_node = chapter.find('.//bibo:Series', namespaces)
    if series_node is not None:
        series_title_node = series_node.find('dcterms:title', namespaces)
        if series_title_node is not None:
            bibo_info['tertiary_title'] = series_title_node.text
        series_number_node = series_node.find('bibo:number', namespaces)
        if series_number_node is not None:
            bibo_info['series_volume'] = series_number_node.text

    reviewed_node = chapter.find('.//bibo:shortTitle', namespaces)
    if reviewed_node is not None:
        bibo_info['reviewed_item'] = reviewed_node.text

    edited_book_node = chapter.find('.//bibo:EditedBook', namespaces)
    if edited_book_node is not None:
        edited_book_title_node = edited_book_node.find('dcterms:title', namespaces)
        if edited_book_title_node is not None:
            bibo_info['secondary_title'] = edited_book_title_node.text

        edited_book_year_node = edited_book_node.find('dcterms:date', namespaces)
        if edited_book_year_node is not None:
            bibo_info['year'] = edited_book_year_node.text

        isbn_node = edited_book_node.find('bibo:isbn13', namespaces)
        if isbn_node is not None:
            bibo_info['issn'] = isbn_node.text

        publisher_node = edited_book_node.find('dcterms:publisher/foaf:Organization', namespaces)
        if publisher_node is not None:
            publisher_name_node = publisher_node.find('foaf:name', namespaces)
            locality_node = publisher_node.find('address:localityName', namespaces)

            if publisher_name_node is not None:
                bibo_info['publisher'] = publisher_name_node.text
            if locality_node is not None:
                bibo_info['place_published'] = locality_node.text
   
    return bibo_info


def _parse_chapter(z_node, author_lookup, keyword_lookup):
    info = {}

    next_node = z_node.getnext()
    if next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}BookSection':
        bibo_node = next_node
    else:
        resource_node = z_node.find('res:resource', namespaces)
        if resource_node is not None:
            bibo_node = resource_node.find('bibo:BookSection', namespaces)
        else:
            bibo_node = z_node.find('bibo:BookSection', namespaces)
    
    if bibo_node is not None:
        info.update(_parse_bibo_chapter(bibo_node, author_lookup))
    
    info.update(_parse_keywords(z_node, keyword_lookup))

    return info

## web pages:
def _parse_bibo_webpage(book, author_lookup):
    bibo_info = {}

    authors = []
    author_list = book.find('.//bibo:authorList/rdf:Seq', namespaces)
    if author_list is not None:
        for li in author_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                authors.append(author_lookup[node_id])
    if authors:
        bibo_info['first_authors'] = authors

    editors = []
    editor_list = book.find('.//bibo:editorList/rdf:Seq', namespaces)
    if editor_list is not None:
        for li in editor_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                editors.append(author_lookup[node_id])
    if editors:
        bibo_info['tertiary_authors'] = editors

    translators = []
    for translator_node in book.findall('.//bibo:translator', namespaces):
        node_id = translator_node.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if node_id in author_lookup:
            translators.append(author_lookup[node_id])
    if translators:
        bibo_info['subsidiary_authors'] = translators

    source_node = book.find('dcterms:source', namespaces)
    if source_node is not None:
        bibo_info['notes_abstract'] = source_node.text

    title_node = book.find('dcterms:title', namespaces)
    if title_node is not None:
        bibo_info['title'] = title_node.text

    date_node = book.find('.//dcterms:date', namespaces)
    if date_node is not None:
        bibo_info['year'] = date_node.text

    uri_node = book.find('bibo:uri', namespaces)
    if uri_node is not None:
        bibo_info['urls'] = uri_node.text
    
    abstract_node = book.find('dcterms:abstract', namespaces)
    if abstract_node is not None:
        bibo_info['abstract'] = abstract_node.text
    
    pages_node = book.find('bibo:numPages', namespaces)
    if parsed_pages := _parse_pages(pages_node):
        for key, val in parsed_pages.items():
            bibo_info[key] = val
    
    isbn_nodes = book.findall('bibo:isbn13', namespaces)
    if isbn_nodes is not None:
        bibo_info['issn'] = ' '.join([inode.text for inode in isbn_nodes])
    
    doi_node = book.find('bibo:doi', namespaces)
    if doi_node is not None:
        bibo_info['doi'] = doi_node.text
    
    reviews_node = book.find('.//dcterms:language', namespaces)
    if reviews_node is not None:
        bibo_info['research_notes'] = reviews_node.text

    volume_node = book.find('bibo:volume', namespaces)
    if volume_node is not None:
        bibo_info['volume'] = volume_node.text

    series_node = book.find('.//bibo:Series', namespaces)
    if series_node is not None:
        series_title_node = series_node.find('dcterms:title', namespaces)
        if series_title_node is not None:
            bibo_info['secondary_title'] = series_title_node.text
        series_number_node = series_node.find('bibo:number', namespaces)
        if series_number_node is not None:
            bibo_info['series_volume'] = series_number_node.text

    reviewed_node = book.find('.//bibo:shortTitle', namespaces)
    if reviewed_node is not None:
        bibo_info['reviewed_item'] = reviewed_node.text

    publisher_node = book.find('{http://purl.org/dc/terms/}publisher/foaf:Organization', namespaces)
    if publisher_node is not None:
        publisher_name_node = publisher_node.find('{http://xmlns.com/foaf/0.1/}name', namespaces)
        locality_node = publisher_node.find('{http://schemas.talis.com/2005/address/schema#}localityName', namespaces)

        if publisher_name_node is not None:
            bibo_info['publisher'] = publisher_name_node.text
        if locality_node is not None:
            bibo_info['place_published'] = locality_node.text
   
    return bibo_info
    
def _parse_web(z_node, author_lookup, keyword_lookup):
    info = {}

    next_node = z_node.getnext()
    if next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Webpage':
        bibo_node = next_node
    else:
        resource_node = z_node.find('{http://purl.org/vocab/resourcelist/schema#}resource')
        if resource_node is not None:
            bibo_node = resource_node.find('{http://purl.org/ontology/bibo/}Webpage')
        else:
            bibo_node = z_node.find('{http://purl.org/ontology/bibo/}Webpage')
    
    if bibo_node is not None:
        info.update(_parse_bibo_webpage(bibo_node, author_lookup))
    
    info.update(_parse_keywords(z_node, keyword_lookup))

    return info

## cdroms etc
def _parse_bibo_film(book, author_lookup):
    bibo_info = {}

    authors = []
    author_list = book.find('.//bibo:authorList/rdf:Seq', namespaces)
    if author_list is not None:
        for li in author_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                authors.append(author_lookup[node_id])
    if authors:
        bibo_info['first_authors'] = authors

    editors = []
    editor_list = book.find('.//bibo:editorList/rdf:Seq', namespaces)
    if editor_list is not None:
        for li in editor_list.findall('rdf:li', namespaces):
            node_id = li.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
            if node_id in author_lookup:
                editors.append(author_lookup[node_id])
    if editors:
        bibo_info['tertiary_authors'] = editors

    translators = []
    for translator_node in book.findall('.//bibo:translator', namespaces):
        node_id = translator_node.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}nodeID')
        if node_id in author_lookup:
            translators.append(author_lookup[node_id])
    if translators:
        bibo_info['subsidiary_authors'] = translators

    source_node = book.find('dcterms:source', namespaces)
    if source_node is not None:
        bibo_info['notes_abstract'] = source_node.text

    title_node = book.find('dcterms:title', namespaces)
    if title_node is not None:
        bibo_info['title'] = title_node.text

    date_node = book.find('.//dcterms:date', namespaces)
    if date_node is not None:
        bibo_info['year'] = date_node.text

    uri_node = book.find('bibo:uri', namespaces)
    if uri_node is not None:
        bibo_info['urls'] = uri_node.text
    
    abstract_node = book.find('dcterms:abstract', namespaces)
    if abstract_node is not None:
        bibo_info['abstract'] = abstract_node.text
    
    pages_node = book.find('bibo:numPages', namespaces)
    if parsed_pages := _parse_pages(pages_node):
        for key, val in parsed_pages.items():
            bibo_info[key] = val

    isbn_nodes = book.findall('bibo:isbn13', namespaces)
    if isbn_nodes is not None:
        bibo_info['issn'] = ' '.join([inode.text for inode in isbn_nodes])
    
    doi_node = book.find('bibo:doi', namespaces)
    if doi_node is not None:
        bibo_info['doi'] = doi_node.text
    
    reviews_node = book.find('bibo:lccn', namespaces)
    if reviews_node is not None and reviews_node.text:
        bibo_info['research_notes'] = reviews_node.text.strip()

    volume_node = book.find('bibo:volume', namespaces)
    if volume_node is not None:
        bibo_info['volume'] = volume_node.text

    series_node = book.find('.//bibo:Series', namespaces)
    if series_node is not None:
        series_title_node = series_node.find('dcterms:title', namespaces)
        if series_title_node is not None:
            bibo_info['secondary_title'] = series_title_node.text
        series_number_node = series_node.find('bibo:number', namespaces)
        if series_number_node is not None:
            bibo_info['series_volume'] = series_number_node.text

    publisher_node = book.find('{http://purl.org/dc/terms/}publisher/foaf:Organization', namespaces)
    if publisher_node is not None:
        publisher_name_node = publisher_node.find('{http://xmlns.com/foaf/0.1/}name', namespaces)
        locality_node = publisher_node.find('{http://schemas.talis.com/2005/address/schema#}localityName', namespaces)

        if publisher_name_node is not None:
            bibo_info['publisher'] = publisher_name_node.text
        if locality_node is not None:
            bibo_info['place_published'] = locality_node.text
   
    return bibo_info
    
def _parse_advs(z_node, author_lookup, keyword_lookup):
    info = {}

    bibo_node = None
    next_node = z_node.getnext()
    if next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Film':
        bibo_node = next_node
    else:
        resource_node = z_node.find('res:resource', namespaces)
        if resource_node is not None:
            bibo_node = resource_node.find('bibo:Film', namespaces)
        else:
            bibo_node = z_node.find('bibo:Film', namespaces)
    
    if bibo_node is not None:
        info.update(_parse_bibo_film(bibo_node, author_lookup))
    
    info.update(_parse_keywords(z_node, keyword_lookup))
    return info


def parse_rdf(rdf_data):
    """"
    takes a file with rdf data and returns parsed ris
    """
    root = etree.fromstring(rdf_data)

    author_lookup = _get_author_lookup(root)
    keyword_lookup = _get_keyword_lookup(root)

    user_items = tuple(root.xpath('//z:UserItem', namespaces=namespaces))

    parsed = []
    for z_node in user_items:
        info = {}

        user_item_url = z_node.xpath('@rdf:about', namespaces=namespaces)
        if user_item_url:
            info['id'] = user_item_url[0]
        else:
            continue
        
        access_date_node = z_node.find('z:accessDate', namespaces)
        if access_date_node is not None:
            info['access_date'] = access_date_node.text
        
        academic_article = z_node.xpath('.//bibo:AcademicArticle', namespaces=namespaces)
        
        if not academic_article:
            resource_url = z_node.xpath('.//res:resource/@rdf:resource', namespaces=namespaces)
            if resource_url:
                try:
                    all_articles = root.xpath("//bibo:AcademicArticle", namespaces=namespaces)
                    academic_article = [article for article in all_articles 
                                     if article.get('{'+namespaces['rdf']+'}about') == resource_url[0]]
                except:
                    academic_article = []

        if academic_article:
            info.update(_parse_jour(z_node, author_lookup=author_lookup, keyword_lookup=keyword_lookup))
            info['type_of_reference'] = 'JOUR'
        
        next_node = z_node.getnext()
        
        if ((next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Book') or 
            z_node.xpath('.//bibo:Book', namespaces=namespaces)):
            info.update(_parse_book(z_node, author_lookup=author_lookup, keyword_lookup=keyword_lookup))
            info['type_of_reference'] = 'BOOK'

            if 'keywords' in info and "speciaal nummer" in set(info['keywords']):
                info['type_of_reference'] = 'JFULL'

        elif ((next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}BookSection') or 
              z_node.xpath('.//bibo:BookSection', namespaces=namespaces)):
            info.update(_parse_chapter(z_node, author_lookup=author_lookup, keyword_lookup=keyword_lookup))
            info['type_of_reference'] = 'CHAP'

        elif ((next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Webpage') or 
              z_node.xpath('.//bibo:Webpage', namespaces=namespaces)):
            info.update(_parse_web(z_node, author_lookup=author_lookup, keyword_lookup=keyword_lookup))
            info['type_of_reference'] = 'WEB'

        elif ((next_node is not None and next_node.tag == '{' + namespaces['bibo'] + '}Film') or 
              z_node.xpath('.//bibo:Film', namespaces=namespaces)):
            info.update(_parse_advs(z_node, author_lookup=author_lookup, keyword_lookup=keyword_lookup))
            info['type_of_reference'] = 'ADVS'

        if info:
            if 'keywords' in info and 'foutmelding (keywords)' in info['keywords']:
                info['keywords'].remove('foutmelding (keywords)')

            if 'urls' in info and not isinstance(info['urls'], list):
                info['urls'] = [info['urls']]
            parsed.append(info)

    # return ris
    parsed = rispy.dumps(parsed, mapping=utils.RISPY_MAPPING)
    return parsed


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('inputdir')
    parser.add_argument('outdir')
    args = parser.parse_args()

    for fn in tqdm(glob(f'{args.inputdir}/*.rdf'), 
            desc="Processing files", 
            position=0,
            leave=True):
        
        parsedf = os.path.basename(fn).replace('.rdf', '.ris')
        parsedf = f'{args.outdir}/{parsedf}'
        with open(fn, 'r', encoding='utf-8') as file:
            parsed = parse_rdf(file.read())
        with open(parsedf, 'w') as bibliography_file:
            bibliography_file.write(parsed)
