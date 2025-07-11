import json
import time
from datetime import datetime, timedelta
import requests
import getpass
import re
from collections import defaultdict

def get_credentials():
    username = "GNMOA"
    password = "GNMOA123"
    #username = input("Enter your username: ")
    #password = getpass.getpass("Enter your password: ")
    return username, password


def fetch_circuits(username, password, payload):
    """Post request to fetch circuits, returns a list of circuit dicts"""
    response = requests.post(
        url = 'https://uts-prod.verizon.com/customerimpacts/api/v2/equipment', 
        json=payload, 
        timeout = (30, 200), 
        auth = (username, password)
    ) 
    return response.json()["results"]


def map_parent_child(circuits):
    """
    Creates a dict that maps each parent to a list of their children. If a ckt has no parent, added as a key with empty list. {parent: [child1, child2]}
     "parentCircuitList": {
                "parentCircuit": [
                    {
                        "parentCircuitId": "121744",
                        "parentCircuitName": "I1001/OTU4/DNVSMAHI/LYNNMACH"
    """
    # parent_child_dict = {}
    ##########################################################################################
    temporary_dict = defaultdict(dict)
    children_with_parents = set()
    ##########################################################################################

    #print(circuits)
    #first iteration to add all potential parents and list circuits that do have parents
    for circuit in circuits:
        parent = None

        #get the parentCircuitList if exists, if otw use empty dict
        parent_list = circuit.get("parentCircuitList", {})

        #get the parentCircuit list from above
        parent_array = parent_list.get("parentCircuit")

        #get child circuit name form current circuit object
        child = circuit["circuitName"]

        ##########################################################################################
        #checks to see if the circuit is a weird circuit that needs to be skipped
        match = re.search("[A-Z]{2} ", child)
        if match:
            continue

        #if parentCircuit exists and is non empty list, extract Name
        if isinstance(parent_array, list) and parent_array:
            potential_parent = parent_array[0].get("parentCircuitName")

            #if the parent is valid and not the circuit itself
            if potential_parent and potential_parent != child:
                parent = potential_parent

        #if a valid parent exists, add to dict
        if parent:
            #assigns the circuit's children under the parent circuit
            temporary_dict[parent][child] = temporary_dict[child]

            #mark this circuit as being a child of another circuit
            children_with_parents.add(child)
        else:
            #if the circuit doesn't have a parent, add as a top-level key
            temporary_dict.setdefault(child, {})
        ##########################################################################################
          
    ##########################################################################################
    parent_child_dict = {}

    #second loop to ensure hierarchy is correct
    for circuit_name, children_dict in temporary_dict.items():

        #circuits that aren't children of others are added as top-level circuits (with their nested children)
        if circuit_name not in children_with_parents:
            parent_child_dict[circuit_name] = dict(children_dict)
    ##########################################################################################

    return parent_child_dict



def find_top_ckts(parent_child_dict):
    """Identifies top lvl ckts (aka those that are not children of any other ckt). Returns a list of ckt names"""
    all_children = {child for children in parent_child_dict.values() for child in children}   #flatten all children into a set
    return [parent for parent in parent_child_dict if parent not in all_children]             #top ckts are those not found in children set


def parse_port_aid(port_aid, raw_shelf, raw_slot, raw_port, card_slot):
    """Parse shelf, slot and port from AID, if the format of AID is unrecognized, falls back to og raw json values"""
    if not port_aid:
        return raw_shelf, raw_slot, raw_port

    ##########################################################################################
    #pattern: dash seperated
    match = re.match(r"^[A-Za-z0-9]+-(\d+)-(\d+)-([A-Za-z0-9]+)", port_aid)
    if match:
        shelf_str, slot_str, port = match.groups()
        shelf, slot = map(int, [shelf_str, slot_str])
        return shelf, slot, port
    
    #pattern: decimal 
    match = re.match(r"(\d+)\.(\d+)", port_aid)
    if match:
        #covers the condition where the slot number has letters and numbers
        if isinstance(card_slot, str):
            slot = card_slot
        else:
            slot = int(match.group(1))
        port = port_aid
        return raw_shelf, slot, port
    ##########################################################################################

    return raw_shelf, raw_slot, raw_port



def extract_endpoint_info(endpoint):
    """Extracts endponit info and validates/corrects slot, shelf and port using AID. Falls back to raw json values when AID format is unrecognized"""

    port_aid = endpoint.get("portAID", "")

    #raw values from json
    raw_shelf = endpoint.get("shelfNumber")
    raw_slot = endpoint.get("slotNumber")
    raw_port = endpoint.get("portNumber")
    ##########################################################################################
    #SOURCED FROM GEMINI
    #retrieve the accurate slot number if available
    card_slot = (
        next (
            (
                attr.get("value") # What we want to return if found
                for attr in endpoint.get("portRefAttributes", {}).get("attribute", [])
                if attr.get("name") == "CARD_SLOT"
            ),
            None #default value if 'CARD_SLOT' isn't found
        )
    )

    #extract correct values using portAID or fall back 
    shelfNumber, slotNumber, portNumber = parse_port_aid(port_aid, raw_shelf, raw_slot, raw_port, card_slot)
    ##########################################################################################

    try:
        #print("inside extract:")
        #print(json.dumps(endpoint, indent=2))
        return {
            "name": endpoint.get("neName"),
            "portAID": port_aid,
            "shelfNumber": shelfNumber,
            "slotNumber": slotNumber,
            "portNumber": portNumber,
            "ipAddress": endpoint["ipAddressLst"][0]["ipAddresses"][0]["ipAddress"]
        }
    
    except (KeyError, IndexError):
        #return None for missing fields
        return {
            "name": None,
            "portAID": None,
            "shelfNumber": None,
            "slotNumber": None,
            "portNumber": None,
            "ipAddress": None
        } 

##########################################################################################
def alternate_extract(endpoint_info, tid, ):
    match = re.match(r"AID=([A-Za-z0-9]+\/\d)\/\d(\/\d)", endpoint_info)
    port_aid = None
    portNumber = None
    if match:
        portNumber = port_aid = match.group(1) + match.group(2)

    return {
        "name": tid,
        "portAID": port_aid,
        "shelfNumber": '0',
        #need to fix later, couldn't find slot number in the API response
        "slotNumber": 'PCIE1',
        "portNumber": portNumber,
        "ipAddress": " "
    }
##########################################################################################
        

def fetch_endpoints(circuit_id):
    """Sends POST request to retrieve endpoint details for a given circuit_id (name, AID, slot, shelf, IP)"""

    payload = {
        "id": circuit_id,
        "system": "GNMOA",
        "sourceSys":"NAUTILUS",
        "clr" : "Y"
        }
    
    response = requests.post(
        url='https://uts-prod.verizon.com/circuitdetailms/api/v2/circuit/detail/b1', 
        json=payload, 
        timeout = (30, 200), 
        auth = ("GNMOA", "GNMOA123")
        )
    
    data = response.json()

    ##########################################################################################
    #flag to keep track of if we got the info
    info_extracted = False
    ##########################################################################################

    try:
        aEnd = data["circuitData"]["circuitLst"][0]["circuit"][0]["aEnd"][0]["portChannel"][0]["portRef"][0]
        zEnd = data["circuitData"]["circuitLst"][0]["circuit"][0]["zEnd"][0]["portChannel"][0]["portRef"][0]
        print('A Endpoint Raw Info:\n', aEnd, '\n')
        print('Z Endpoint Raw Info:\n', zEnd, '\n')
        #extract details using helper function
        aEndInfo = extract_endpoint_info(aEnd)
        zEndInfo = extract_endpoint_info(zEnd)
        print('A Extracted Info:\n', aEndInfo, '\n')
        print('Z Extracted Info:\n', zEndInfo, '\n')

        print(f"\nCircuit ID: {circuit_id}")

        print("A-End Info:")
        for k, v in aEndInfo.items():
            print(f"  {k}:  {v}")

        print("Z-End Info:")
        for k, v in zEndInfo.items():
            print(f"  {k}:  {v}")
        print('\n')
        
        info_extracted = True

    ##########################################################################################
    except (KeyError, IndexError):
        print(f"\nCircuit ID: {circuit_id} - Primary portRef extraction failed. Attempting SNC data extraction...")
        
        try:
            snc_data = data["circuitData"]["circuitLst"][0]["circuit"][0]["sncData"]["details"]
            aEnd_tid = None
            zEnd_tid = None
            zEnd_info = None

            for block in snc_data:
                current_aEnd_tid = block.get("aendDeviceId")
                if isinstance(current_aEnd_tid, str) and re.match(r"[A-Z]+-[0-9]+", current_aEnd_tid):
                    aEnd_tid = current_aEnd_tid
                    break

            for block in snc_data:
                current_zEnd_tid = block.get("zendDeviceId")
                if isinstance(current_zEnd_tid, str) and re.match(r"[A-Z]+-[0-9]+", current_zEnd_tid):
                    zEnd_tid = current_zEnd_tid
                    break 

            if aEnd_tid and zEnd_tid:
                for block in snc_data:
                     current_zEnd_info = block.get("zprimaryEndpointInfo")
                     if isinstance(current_zEnd_info, str) and re.match(r"AID=[a-zA-Z0-9\/]+", current_zEnd_info):
                         zEnd_info = current_zEnd_info
                         break
                     
                if aEnd_tid == zEnd_tid:
                    print(f"Circuit ID: {circuit_id} - SNC data fallback: A-End TID and Z-End TID match.")

                    aEnd = data["circuitData"]["circuitLst"][0]["circuit"][0]["aEnd"][0]["portChannel"][0]["portRef"][0]
                    print('A Endpoint Raw Info:\n', aEnd, '\n')
                    print('Z Endpoint Raw Info: (inaccessible) the same as aEnd\n', '\n')
                    #extract details using helper function
                    aEndInfo = extract_endpoint_info(aEnd)
                    print('A Extracted Info:\n', aEndInfo, '\n')

                    print(f"\nCircuit ID: {circuit_id}")

                    print("A-End Info:")
                    for k, v in aEndInfo.items():
                        print(f"  {k}:  {v}")

                    print("\nZ-End Info:\n  the same as aEnd \n\n")
                    info_extracted = True

                else:
                    if isinstance(zEnd_info, str):
                        zEnd_ip = None
                        try:
                            aEnd = data["circuitData"]["circuitLst"][0]["circuit"][0]["aEnd"][0]["portChannel"][0]["portRef"][0]
                            print('A Endpoint Raw Info:\n', aEnd, '\n')
                            print('Z Endpoint Raw Info:\nInfo: ', zEnd_info, '\nTID: ', zEnd_tid, '\nIP: ', zEnd_ip, '\n')

                            #extract details using helper function
                            aEndInfo = extract_endpoint_info(aEnd)
                            zEndInfo = alternate_extract(zEnd_info, zEnd_tid)

                            print('A Extracted Info:\n', aEndInfo, '\n')
                            print('Z Extracted Info:\n', zEndInfo, '\n')

                            print(f"\nCircuit ID: {circuit_id}")

                            print("A-End Info:")
                            for k, v in aEndInfo.items():
                                print(f"  {k}:  {v}")

                            print("Z-End Info:")
                            for k, v in zEndInfo.items():
                                print(f"  {k}:  {v}")
                            print('\n')

                            info_extracted = True
                            
                        except (KeyError, IndexError):
                            print(f"\nCircuit ID: {circuit_id} - SNC data fallback: Endpoint TIDs are different ({aEnd_tid} vs {zEnd_tid}) but can't retrieve full info.")
                            raise ValueError(f"SNC data fallback: Endpoint TIDs are different ({aEnd_tid} vs {zEnd_tid}) but can't retrieve full info.")
                    else:
                        print(f"\nCircuit ID: {circuit_id} - SNC data fallback: Endpoint TIDs are different ({aEnd_tid} vs {zEnd_tid}) but can't retrieve full info.")
                        raise ValueError(f"SNC data fallback: Endpoint TIDs are different ({aEnd_tid} vs {zEnd_tid}) but can't retrieve full info.")
            else:
                print(f"\nCircuit ID: {circuit_id} - SNC data fallback: Endpoint TIDs unable to retrieve or did not match pattern.")
                raise ValueError("SNC data fallback: Endpoint TIDs unable to retrieve or did not match pattern.")
        except (KeyError, IndexError, ValueError):
            print(f"\nCircuit ID: {circuit_id} - SNC data fallback also failed")
    
    if not info_extracted:
        print(f"\nCircuit ID: {circuit_id} - Endpoint data N/A for all attempts.")
    ##########################################################################################

def main():
    """
    Steps:
    1. Get login info
    2. Fetches all circuit data
    3. Maps parents to children
    4. Identifies top lvl ckts
    5. Fetches and prints endpoint info for each top lvl ckt
    """

    #Step 1: Get login 
    username, password = get_credentials()

    #Step 2: Fetch all circuit data
    payload = {
        "tid": "WSPTMADR-0112106A",
        "shelfName": "21",
        "slotName": "5",       
        "system": "GNMOA"
    }

    circuits = fetch_circuits(username, password, payload)

    #Step 3: Mapping parent to children
    parent_child_dict = map_parent_child(circuits)
    print("Parent to Children mapping:")
    print(json.dumps(parent_child_dict, indent=2))


    #Step 4: Find all top level circuits
    top_circuits = find_top_ckts(parent_child_dict)
    print("\nTop Level Circuits:")
    print(top_circuits)

    #Step 5: Get endpoint info and print
    print("\nEndpoint details for top circuits:\n")
    for circuit_id in top_circuits:
        fetch_endpoints(circuit_id)


if __name__ == '__main__':
    main()

























# def circuit_details_new(self, cid='', mode='', sys=None):
#     if not cid:
#         return 'bad', None, 'A complete and valid circuit ID is required.'
#     cid = unquote_plus(cid)
#     url = f"{self.burl}circuitdetailms/api/v2/circuit/detail/GNMOA/b1?"
#     if mode == 'clr':
#         if sys:
#             url = f"{url}id={cid}&clr=Y&sourceSys={sys}"
#         else:
#             url = f"{url}id={cid}&clr=Y"
#     else:
#         if sys:
#             url = f"{url}id={cid}&circuitAttr=Y&cust=Y&diversity=Y&firstLvlRiderLst=Y&CircuitAliasLst=" \
#                 f"Y&muxMsgData=Y&stitched=Y&clr=Y&sourceSys={sys}"
#         else:
#             url = f"{url}id={cid}&circuitAttr=Y&cust=Y&diversity=Y&firstLvlRiderLst=Y&CircuitAliasLst=" \
#                 f"Y&muxMsgData=Y&stitched=Y&clr=Y"
